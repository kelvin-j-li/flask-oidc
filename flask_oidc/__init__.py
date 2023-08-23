# Copyright (c) 2014-2015, Erica Ehrhardt
# Copyright (c) 2016, Patrick Uiterwijk <patrick@puiterwijk.org>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import json
import logging
import time
import warnings
from functools import wraps
from urllib.parse import quote_plus

from authlib.integrations.flask_client import OAuth
from authlib.integrations.flask_oauth2 import ResourceProtector
from authlib.oauth2.rfc7662 import (
    IntrospectTokenValidator as BaseIntrospectTokenValidator,
)
from flask import (
    abort,
    current_app,
    g,
    redirect,
    request,
    session,
    url_for,
)

from .views import auth_routes, legacy_oidc_callback

__all__ = ["OpenIDConnect"]

_CONFIG_REMOVED = (
    "OIDC_GOOGLE_APPS_DOMAIN",
    "OIDC_REQUIRE_VERIFIED_EMAIL",
    "OIDC_RESOURCE_CHECK_AUD",
    "OIDC_VALID_ISSUERS",
)
_CONFIG_DEPRECATED = (
    "OIDC_ID_TOKEN_COOKIE_NAME",
    "OIDC_ID_TOKEN_COOKIE_PATH",
    "OIDC_ID_TOKEN_COOKIE_TTL",
    "OIDC_COOKIE_SECURE",
    "OIDC_OPENID_REALM",
    "OVERWRITE_REDIRECT_URI",
    "OIDC_CALLBACK_ROUTE",
    "OIDC_USERINFO_URL",
)

logger = logging.getLogger(__name__)


class IntrospectTokenValidator(BaseIntrospectTokenValidator):
    """Validates a token using introspection."""

    def introspect_token(self, token_string):
        """Return the token introspection result."""
        oauth = g._oidc_auth
        metadata = oauth.load_server_metadata()
        if "introspection_endpoint" not in metadata:
            raise RuntimeError(
                "Can't validate the token because the server does not support "
                "introspection."
            )
        with oauth._get_oauth_client(**metadata) as session:
            response = session.introspect_token(
                metadata["introspection_endpoint"], token=token_string
            )
        return response.json()


class OpenIDConnect:
    accept_token = ResourceProtector()

    def __init__(
        self,
        app=None,
        credentials_store=None,
        http=None,
        time=None,
        urandom=None,
        prefix=None,
    ):
        for param_name in ("credentials_store", "http", "time", "urandom"):
            if locals()[param_name] is not None:
                warnings.warn(
                    f"The {param_name!r} attibute is no longer used.",
                    DeprecationWarning,
                    stacklevel=2,
                )
        self.accept_token.register_token_validator(IntrospectTokenValidator())
        if app is not None:
            self.init_app(app, prefix=prefix)

    def init_app(self, app, prefix=None):
        # Removed features, die if still there
        for param in _CONFIG_REMOVED:
            if param in app.config:
                raise ValueError(
                    f"The {param!r} configuration value is no longer enforced."
                )
        # Deprecated config values, harmless if still there
        for param in _CONFIG_DEPRECATED:
            if param in app.config:
                warnings.warn(
                    f"The {param!r} configuration value is deprecated and ignored.",
                    DeprecationWarning,
                    stacklevel=2,
                )

        secrets = self.load_secrets(app)
        self.client_secrets = list(secrets.values())[0]

        app.config.setdefault("OIDC_CLIENT_ID", self.client_secrets["client_id"])
        app.config.setdefault(
            "OIDC_CLIENT_SECRET", self.client_secrets["client_secret"]
        )
        app.config.setdefault("OIDC_USER_INFO_ENABLED", True)
        app.config.setdefault("OIDC_INTROSPECTION_AUTH_METHOD", "client_secret_post")
        app.config.setdefault("OIDC_CLOCK_SKEW", 60)
        app.config.setdefault("OIDC_RESOURCE_SERVER_ONLY", False)
        app.config.setdefault("OIDC_CALLBACK_ROUTE", "/oidc_callback")

        app.config.setdefault("OIDC_SCOPES", "openid profile email")
        if "openid" not in app.config["OIDC_SCOPES"]:
            raise ValueError('The value "openid" must be in the OIDC_SCOPES')
        if isinstance(app.config["OIDC_SCOPES"], (list, tuple)):
            warnings.warn(
                "The OIDC_SCOPES configuration value should now be a string",
                DeprecationWarning,
                stacklevel=2,
            )
            app.config["OIDC_SCOPES"] = " ".join(app.config["OIDC_SCOPES"])

        provider_url = self.client_secrets["issuer"].rstrip("/")
        app.config.setdefault(
            "OIDC_SERVER_METADATA_URL",
            f"{provider_url}/.well-known/openid-configuration",
        )

        self.oauth = OAuth(app)
        self.oauth.register(
            name="oidc",
            server_metadata_url=app.config["OIDC_SERVER_METADATA_URL"],
            client_kwargs={
                "scope": app.config["OIDC_SCOPES"],
                "token_endpoint_auth_method": app.config[
                    "OIDC_INTROSPECTION_AUTH_METHOD"
                ],
            },
        )

        if not app.config["OIDC_RESOURCE_SERVER_ONLY"]:
            app.register_blueprint(auth_routes, url_prefix=prefix)
            app.route(app.config["OIDC_CALLBACK_ROUTE"])(legacy_oidc_callback)
        app.before_request(self._before_request)

    def load_secrets(self, app):
        # Load client_secrets.json to pre-initialize some configuration
        content_or_filepath = app.config["OIDC_CLIENT_SECRETS"]
        if isinstance(content_or_filepath, dict):
            return content_or_filepath
        else:
            with open(content_or_filepath) as f:
                return json.load(f)

    def _before_request(self):
        g._oidc_auth = self.oauth.oidc
        if not current_app.config["OIDC_RESOURCE_SERVER_ONLY"]:
            return self.check_token_expiry()

    def check_token_expiry(self):
        try:
            token = session.get("oidc_auth_token")
            if not token:
                return
            clock_skew = current_app.config["OIDC_CLOCK_SKEW"]
            if token["expires_at"] - clock_skew < int(time.time()):
                return redirect("{}?reason=expired".format(url_for("oidc_auth.logout")))
        except Exception as e:
            session.pop("oidc_auth_token", None)
            session.pop("oidc_auth_profile", None)
            logger.exception("Could not check token expiration")
            abort(500, f"{e.__class__.__name__}: {e}")

    @property
    def user_loggedin(self):
        """
        Represents whether the user is currently logged in.

        Returns:
            bool: Whether the user is logged in with Flask-OIDC.

        .. versionadded:: 1.0
        """
        return session.get("oidc_auth_token") is not None

    def user_getinfo(self, fields, access_token=None):
        if not current_app.config["OIDC_USER_INFO_ENABLED"]:
            raise RuntimeError(
                "User info is disabled in configuration (OIDC_USER_INFO_ENABLED)"
            )
        if access_token is not None:
            warnings.warn(
                "Calling user_getinfo with a token is deprecated, please use "
                "g._oidc_auth.userinfo(token=token)",
                DeprecationWarning,
                stacklevel=2,
            )
            return self.oauth.oidc.userinfo(token=access_token)
        warnings.warn(
            "The user_getinfo method is deprecated, please use "
            "session['oidc_auth_profile']",
            DeprecationWarning,
            stacklevel=2,
        )
        if not self.user_loggedin:
            abort(401, "User was not authenticated")
        return session.get("oidc_auth_profile", {})

    def user_getfield(self, field, access_token=None):
        """
        Request a single field of information about the user.

        :param field: The name of the field requested.
        :type field: str
        :returns: The value of the field. Depending on the type, this may be
            a string, list, dict, or something else.
        :rtype: object

        .. versionadded:: 1.0
        """
        warnings.warn(
            "The user_getfield method is deprecated, all the user info is in "
            "session['oidc_auth_profile']",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.user_getinfo([field]).get(field)

    def get_access_token(self):
        """Method to return the current requests' access_token.

        :returns: Access token or None
        :rtype: str

        .. versionadded:: 1.2
        """
        return session.get("oidc_auth_token", {}).get("access_token")

    def get_refresh_token(self):
        """Method to return the current requests' refresh_token.

        :returns: Access token or None
        :rtype: str

        .. versionadded:: 1.2
        """
        return session.get("oidc_auth_token", {}).get("refresh_token")

    def require_login(self, view_func):
        """
        Use this to decorate view functions that require a user to be logged
        in. If the user is not already logged in, they will be sent to the
        Provider to log in, after which they will be returned.

        .. versionadded:: 1.0
           This was :func:`check` before.
        """

        @wraps(view_func)
        def decorated(*args, **kwargs):
            if not self.user_loggedin:
                redirect_uri = "{login}?next={here}".format(
                    login=url_for("oidc_auth.login"),
                    here=quote_plus(request.url),
                )
                return redirect(redirect_uri)
            return view_func(*args, **kwargs)

        return decorated

    def logout(self, return_to=None):
        """
        Request the browser to please forget the cookie we set, to clear the
        current session.

        Note that as described in [1], this will not log out in the case of a
        browser that doesn't clear cookies when requested to, and the user
        could be automatically logged in when they hit any authenticated
        endpoint.

        [1]: https://github.com/puiterwijk/flask-oidc/issues/5#issuecomment-86187023

        .. versionadded:: 1.0
        """
        return_to = return_to or request.root_url
        warnings.warn(
            "The logout method is deprecated, just redirect to {}".format(
                url_for("oidc_auth.logout", next=return_to)
            ),
            DeprecationWarning,
            stacklevel=2,
        )
        return redirect(url_for("oidc_auth.logout", next=return_to))

    def custom_callback(self, *args, **kwargs):
        raise ValueError("This feature has been dropped")
