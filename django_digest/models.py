from __future__ import absolute_import, unicode_literals

import django
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db import models
from django.db.models.signals import post_save
from django_digest.utils import get_backend, get_setting, DEFAULT_REALM
from python_digest import calculate_partial_digest


User = get_user_model()


class UserNonce(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    nonce = models.CharField(max_length=100, unique=True, db_index=True)
    count = models.IntegerField(null=True)
    last_used_at = models.DateTimeField(null=False)

    class Meta(object):
        app_label = 'django_digest'
        ordering = ('last_used_at',)


class PartialDigest(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    login = models.CharField(max_length=128, db_index=True)
    partial_digest = models.CharField(max_length=100)
    confirmed = models.BooleanField(default=True)

    class Meta(object):
        app_label = 'django_digest'


_postponed_partial_digests = {}


def _get_logins(user, method_name):
    login_factory = get_backend(
        'DIGEST_LOGIN_FACTORY', 'django_digest.DefaultLoginFactory'
    )
    method = getattr(login_factory, method_name, None)
    if method:
        return set(method(user))
    else:
        return set()


def _confirmed_logins(user):
    return _get_logins(user, 'confirmed_logins_for_user')


def _unconfirmed_logins(user):
    return _get_logins(user, 'unconfirmed_logins_for_user')


def _store_partial_digests(user):
    PartialDigest.objects.filter(user=user).delete()
    for login, partial_digest, confirmed in _postponed_partial_digests[
        user.password
    ]:
        PartialDigest.objects.create(
            user=user,
            login=login,
            confirmed=confirmed,
            partial_digest=partial_digest,
        )


def _prepare_partial_digests(user, raw_password):
    if raw_password is None:
        return
    realm = get_setting('DIGEST_REALM', DEFAULT_REALM)
    partial_digests = []
    for confirmed, factory_method in (
        (True, _confirmed_logins),
        (False, _unconfirmed_logins),
    ):
        partial_digests += [
            (
                login,
                calculate_partial_digest(login, realm, raw_password),
                confirmed,
            )
            for login in factory_method(user)
        ]

    password_hash = user.password
    _postponed_partial_digests[password_hash] = partial_digests


_old_set_password = User.set_password
_old_check_password = User.check_password
_old_create_user = type(User.objects)._create_user
_old_authenticate = ModelBackend.authenticate


def _review_partial_digests(user):
    confirmed_logins = _confirmed_logins(user)
    unconfirmed_logins = _unconfirmed_logins(user)

    for pd in PartialDigest.objects.filter(user=user):
        if pd.login in confirmed_logins:
            if not pd.confirmed:
                pd.confirmed = True
                pd.save()
        elif pd.login in unconfirmed_logins:
            if pd.confirmed:
                pd.confirmed = False
                pd.save()
        else:
            pd.delete()


def _after_authenticate(user, password):
    for confirmed, factory_method in (
        (True, _confirmed_logins),
        (False, _unconfirmed_logins),
    ):
        logins = factory_method(user)
        # if we don't have all of these logins
        # and exactly these logins in the database
        db_logins = set(
            [
                pd.login
                for pd in PartialDigest.objects.filter(
                    user=user, confirmed=confirmed
                )
            ]
        )
        if db_logins != logins:
            _prepare_partial_digests(user, password)
            _persist_partial_digests(user)
            return


def _new_check_password(user, raw_password):
    result = _old_check_password(user, raw_password)
    if result:
        _after_authenticate(user, raw_password)
    return result


def _new_authenticate(backend, request, username=None, password=None):
    user = _old_authenticate(backend, request, username, password)
    if user:
        _after_authenticate(user, password)
    return user


def _new_authenticate_pre_1_11(backend, username=None, password=None):
    user = _old_authenticate(backend, username, password)
    if user:
        _after_authenticate(user, password)
    return user


def _new_set_password(user, raw_password):
    _old_set_password(user, raw_password)
    _prepare_partial_digests(user, raw_password)


def _new_create_user(self, username, email, password, **extra):
    user = _old_create_user(self, username, email, password, **extra)
    _prepare_partial_digests(user, password)
    _persist_partial_digests(user)
    return user


User.check_password = _new_check_password
User.set_password = _new_set_password
if django.VERSION[0] > 2:
    type(User.objects)._create_user = _new_create_user
if django.VERSION >= (1, 11):
    ModelBackend.authenticate = _new_authenticate
else:
    ModelBackend.authenticate = _new_authenticate_pre_1_11


def _persist_partial_digests(user):
    password_hash = user.password
    if password_hash in _postponed_partial_digests:
        _store_partial_digests(user)
        del _postponed_partial_digests[password_hash]


def _post_save_persist_partial_digests(sender, instance=None, **kwargs):
    if instance is not None:
        _persist_partial_digests(instance)


post_save.connect(_post_save_persist_partial_digests, sender=User)
