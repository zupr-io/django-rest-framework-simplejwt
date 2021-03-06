from __future__ import unicode_literals

from datetime import timedelta

from django.test import TestCase
from mock import patch
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer, TokenObtainSerializer,
    TokenObtainSlidingSerializer, TokenRefreshSerializer,
    TokenRefreshSlidingSerializer
)
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.state import User
from rest_framework_simplejwt.tokens import (
    AccessToken, RefreshToken, SlidingToken
)
from rest_framework_simplejwt.utils import (
    aware_utcnow, datetime_from_epoch, datetime_to_epoch
)


class TestTokenObtainSerializer(TestCase):
    def setUp(self):
        self.username = 'test_user'
        self.password = 'test_password'

        self.user = User.objects.create_user(
            username=self.username,
            password=self.password,
        )

    def test_it_should_not_validate_if_any_fields_missing(self):
        s = TokenObtainSerializer(data={})
        self.assertFalse(s.is_valid())
        self.assertIn(s.username_field, s.errors)
        self.assertIn('password', s.errors)

        s = TokenObtainSerializer(data={
            TokenObtainSerializer.username_field: 'oieanrst',
        })
        self.assertFalse(s.is_valid())
        self.assertIn('password', s.errors)

        s = TokenObtainSerializer(data={
            'password': 'oieanrst',
        })
        self.assertFalse(s.is_valid())
        self.assertIn(s.username_field, s.errors)

    def test_it_should_not_validate_if_user_not_found(self):
        s = TokenObtainSerializer(data={
            TokenObtainSerializer.username_field: 'missing',
            'password': 'pass',
        })

        self.assertFalse(s.is_valid())
        self.assertIn('non_field_errors', s.errors)

    def test_it_should_not_validate_if_user_not_active(self):
        self.user.is_active = False
        self.user.save()

        s = TokenObtainSerializer(data={
            TokenObtainSerializer.username_field: self.username,
            'password': self.password,
        })

        self.assertFalse(s.is_valid())
        self.assertIn('non_field_errors', s.errors)


class TestTokenObtainSlidingSerializer(TestCase):
    def setUp(self):
        self.username = 'test_user'
        self.password = 'test_password'

        self.user = User.objects.create_user(
            username=self.username,
            password=self.password,
        )

    def test_it_should_produce_a_json_web_token_when_valid(self):
        s = TokenObtainSlidingSerializer(data={
            TokenObtainSlidingSerializer.username_field: self.username,
            'password': self.password,
        })

        self.assertTrue(s.is_valid())
        self.assertIn('token', s.validated_data)

        # Expecting token type claim to be correct for sliding token.  If this
        # is the case, instantiating a `SlidingToken` instance with encoded
        # token should not raise an exception.
        SlidingToken(s.validated_data['token'])


class TestTokenObtainPairSerializer(TestCase):
    def setUp(self):
        self.username = 'test_user'
        self.password = 'test_password'

        self.user = User.objects.create_user(
            username=self.username,
            password=self.password,
        )

    def test_it_should_produce_a_json_web_token_when_valid(self):
        s = TokenObtainPairSerializer(data={
            TokenObtainPairSerializer.username_field: self.username,
            'password': self.password,
        })

        self.assertTrue(s.is_valid())
        self.assertIn('access', s.validated_data)
        self.assertIn('refresh', s.validated_data)

        # Expecting token type claim to be correct for both tokens.  If this is
        # the case, instantiating appropriate token subclass instances with
        # encoded tokens should not raise an exception.
        AccessToken(s.validated_data['access'])
        RefreshToken(s.validated_data['refresh'])


class TestTokenRefreshSlidingSerializer(TestCase):
    def test_it_should_not_validate_if_token_invalid(self):
        token = SlidingToken()
        del token['exp']

        s = TokenRefreshSlidingSerializer(data={'token': str(token)})
        self.assertFalse(s.is_valid())
        self.assertIn('non_field_errors', s.errors)
        self.assertIn("has no 'exp' claim", s.errors['non_field_errors'][0])

        token.set_exp(lifetime=-timedelta(days=1))

        s = TokenRefreshSlidingSerializer(data={'token': str(token)})
        self.assertFalse(s.is_valid())
        self.assertIn('non_field_errors', s.errors)
        self.assertIn('invalid or expired', s.errors['non_field_errors'][0])

    def test_it_should_not_validate_if_token_has_no_refresh_exp_claim(self):
        token = SlidingToken()
        del token[api_settings.SLIDING_TOKEN_REFRESH_EXP_CLAIM]

        s = TokenRefreshSlidingSerializer(data={'token': str(token)})
        self.assertFalse(s.is_valid())
        self.assertIn('non_field_errors', s.errors)
        self.assertIn("has no '{}' claim".format(api_settings.SLIDING_TOKEN_REFRESH_EXP_CLAIM), s.errors['non_field_errors'][0])

    def test_it_should_not_validate_if_token_has_refresh_period_expired(self):
        token = SlidingToken()
        token.set_exp(api_settings.SLIDING_TOKEN_REFRESH_EXP_CLAIM, lifetime=-timedelta(days=1))

        s = TokenRefreshSlidingSerializer(data={'token': str(token)})
        self.assertFalse(s.is_valid())
        self.assertIn('non_field_errors', s.errors)
        self.assertIn("'{}' claim has expired".format(api_settings.SLIDING_TOKEN_REFRESH_EXP_CLAIM), s.errors['non_field_errors'][0])

    def test_it_should_not_validate_if_token_has_wrong_type(self):
        token = SlidingToken()
        token[api_settings.TOKEN_TYPE_CLAIM] = 'wrong_type'

        s = TokenRefreshSlidingSerializer(data={'token': str(token)})
        self.assertFalse(s.is_valid())
        self.assertIn('non_field_errors', s.errors)
        self.assertIn("wrong type", s.errors['non_field_errors'][0])

    def test_it_should_update_token_exp_claim_if_everything_ok(self):
        old_token = SlidingToken()

        lifetime = api_settings.SLIDING_TOKEN_LIFETIME - timedelta(seconds=1)
        old_exp = old_token.current_time + lifetime

        old_token.set_exp(lifetime=lifetime)

        # Serializer validates
        s = TokenRefreshSlidingSerializer(data={'token': str(old_token)})
        self.assertTrue(s.is_valid())

        # Expiration claim has moved into future
        new_token = SlidingToken(s.validated_data['token'])
        new_exp = datetime_from_epoch(new_token['exp'])

        self.assertTrue(old_exp < new_exp)


class TestTokenRefreshSerializer(TestCase):
    def test_it_should_not_validate_if_token_invalid(self):
        token = RefreshToken()
        del token['exp']

        s = TokenRefreshSerializer(data={'refresh': str(token)})
        self.assertFalse(s.is_valid())
        self.assertIn('non_field_errors', s.errors)
        self.assertIn("has no 'exp' claim", s.errors['non_field_errors'][0])

        token.set_exp(lifetime=-timedelta(days=1))

        s = TokenRefreshSerializer(data={'refresh': str(token)})
        self.assertFalse(s.is_valid())
        self.assertIn('non_field_errors', s.errors)
        self.assertIn('invalid or expired', s.errors['non_field_errors'][0])

    def test_it_should_not_validate_if_token_has_wrong_type(self):
        token = RefreshToken()
        token[api_settings.TOKEN_TYPE_CLAIM] = 'wrong_type'

        s = TokenRefreshSerializer(data={'refresh': str(token)})
        self.assertFalse(s.is_valid())
        self.assertIn('non_field_errors', s.errors)
        self.assertIn("wrong type", s.errors['non_field_errors'][0])

    def test_it_should_return_access_token_if_everything_ok(self):
        refresh = RefreshToken()
        refresh['test_claim'] = 'arst'

        # Serializer validates
        s = TokenRefreshSerializer(data={'refresh': str(refresh)})

        now = aware_utcnow() - api_settings.ACCESS_TOKEN_LIFETIME / 2

        with patch('rest_framework_simplejwt.tokens.aware_utcnow') as fake_aware_utcnow:
            fake_aware_utcnow.return_value = now
            self.assertTrue(s.is_valid())

        access = AccessToken(s.validated_data['access'])

        self.assertEqual(refresh['test_claim'], access['test_claim'])
        self.assertEqual(access['exp'], datetime_to_epoch(now + api_settings.ACCESS_TOKEN_LIFETIME))
