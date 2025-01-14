==========
Flask-OIDC
==========

Flask-OIDC is an extension to `Flask`_ that allows you to add `OpenID Connect`_
based authentication to your website in a matter of minutes. It depends
on Flask and `Authlib`_. You can install the requirements from PyPI with `pip`.

.. _Flask: http://flask.pocoo.org/
.. _OpenID Connect: https://openid.net/connect/
.. _Authlib: https://authlib.org/


Features:

- Support for OpenID Connect 1.0
- Support for OpenID Connect Discovery 1.0
- Support for OpenID Connect Dynamic Registration 1.0
- Friendly API
- Perfect integration into Flask
- Helper functions to allow resource servers to accept OAuth2 tokens



How to use
==========

Installation
------------
Install the extension with `pip`::

    $ pip install Flask-OIDC

Integration
-----------
To integrate Flask-OpenID into your application you need to create an
instance of the :class:`OpenID` object first::

    from flask_oidc import OpenIDConnect
    oidc = OpenIDConnect(app)

Alternatively the object can be instantiated without the application in
which case it can later be registered for an application with the
:meth:`~flask_oidc.OpenIDConnect.init_app` method.

Using this library is very simple: you can use
:data:`~flask_oidc.OpenIDConnect.user_loggedin` to determine whether a user is currently
logged in using OpenID Connect.

If the user is logged in, you an use ``session["oidc_auth_profile"]`` to get
information about the currently logged in user.

You can decorate any view function with :meth:`~flask_oidc.OpenIDConnect.require_login`
to redirect anonymous users to the OIDC provider.


Example
-------
A very basic example client::

    @app.route('/')
    def index():
        if oidc.user_loggedin:
            return 'Welcome %s' % session["oidc_auth_profile"].get('email')
        else
            return 'Not logged in'

    @app.route('/login')
    @oidc.require_login
    def login():
        return 'Welcome %s' % session["oidc_auth_profile"].get('email')


Resource server
===============

Also, if you have implemented an API that should be able to accept tokens
issued by the OpenID Connect provider, just decorate those API functions with
:meth:`~flask_oidc.OpenIDConnect.accept_token`::

    from authlib.integrations.flask_oauth2 import current_token

    @app.route('/api')
    @oidc.accept_token()
    def my_api():
        return json.dumps(f'Welcome {current_token["sub"]}')

The current token is available via the ``current_token`` proxy object in
``authlib.integrations.flask_oauth2``.
Information about the user can be retrieved using the ``userinfo()`` method,
providing the current token.

The :meth:`~flask_oidc.OpenIDConnect.accept_token` decorator also accepts a
list of required scopes that the token must provide::

    from authlib.integrations.flask_oauth2 import current_token

    @app.route('/api')
    @oidc.accept_token(scopes=['profile'])
    def my_api():
        profile = g._oidc_auth.userinfo(token=current_token)
        return json.dumps(f'Welcome {profile["fullname"]}')

This decorator is an Authlib `ResourceProtector`_, you'll find more
documentation on their website.

.. _ResourceProtector: https://docs.authlib.org/en/latest/flask/2/resource-server.html


Registration
============

To be able to use an OpenID Provider, you will need to register your client
with them.
If the Provider you want to use supports Dynamic Registration, you can install
the `oidc-register package <https://pypi.org/project/oidc-register/>`_ and
execute::

    oidc-register https://myprovider.example.com/ https://myapplication.example.com/authorize

The full ``client_secrets.json`` file will be generated for you, and you are
ready to start.

If it does not, please see the documentation of the Provider you want to use
for information on how to obtain client secrets.

For example, for Google, you will need to visit `Google API credentials management
<https://console.developers.google.com/apis/credentials?project=_>`_.


Manual client registration
--------------------------

If your identity provider does not offer Dynamic Registration (and you can't
push them to do so, as it would make it a lot simpler!), you might need to know
the following details:

  Grant type
    authorization_code (Authorization Code flow)

  Response type
    Code

  Token endpoint auth metod
    client_secret_post

  Redirect URI
    <APPLICATION_URL>/authorize


You will also need to manually craft your ``client_secrets.json``.
This is just a json document, with everything under a top-level "web" key.
Underneath that top-level key, you have the following keys:

  client_id
    Client ID issued by your IdP

  client_secret
    Client secret belonging to the registered ID

  auth_uri
    The Identity Provider's authorization endpoint url

  token_uri
    The Identity Provider's token endpoint url
    (Optional, used for resource server)

  userinfo_uri
    The Identity Provider's userinfo url

  issuer
    The "issuer" value for the Identity Provider

  redirect_uris
    A list of the registered redirect uris


Settings reference
==================

This is a list of all settings supported in the current release.

  OIDC_SCOPES
    A string containing the scopes that should be requested separated by spaces.
    This impacts the information available in the ``oidc_auth_profile`` session
    value and what the token can be used for. Please check your identity
    provider's documentation for valid values.
    Defaults to ``"openid email"``.

  OIDC_CLOCK_SKEW
    Number of seconds of clock skew allowed when checking the "don't use
    before" and "don't use after" values for tokens.
    Defaults to sixty seconds (one minute).

  OIDC_USER_INFO_ENABLED
    Boolean whether to get user information from the UserInfo endpoint provided
    by the Identity Provider in addition to the token information.
    Defaults to True.

  OIDC_RESOURCE_SERVER_ONLY
    Boolean whether to disable the OpenID Client parts. You can enable this
    in applications where you only use the resource server parts (accept_token)
    and will skip checking for any cookies.

  OIDC_INTROSPECTION_AUTH_METHOD
    String that sets the authentication method used when communicating with
    the token_introspection_uri.  Valid values are 'client_secret_post',
    'client_secret_basic', or 'bearer'.  Defaults to 'client_secret_post'.


Other docs
==========

.. toctree::
   API Reference <_source/flask_oidc>
   changelog
