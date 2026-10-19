"""
Program Name: PixelSentinel Web

Description:
Private enrollment web service for PixelSentinel push notifications.

There is intentionally no public home page.
Users access the service only through private enrollment URLs.
"""

import os
import sqlite3
import hashlib
import json
import logging
import ipaddress
import socket
import requests

from datetime import datetime, timezone
from flask import Flask, render_template, abort, jsonify, make_response, send_from_directory, url_for, request
from dotenv import load_dotenv
from pywebpush import webpush, WebPushException
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_FILE = os.path.join(BASE_DIR,"pixelsentinel.db")

ENV_FILE = os.path.join(BASE_DIR,".env")

load_dotenv(ENV_FILE)

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY","").strip()

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY","").strip()

VAPID_SUBJECT = os.getenv("VAPID_SUBJECT","").strip()

ADMIN_ALERT_EMAIL = os.getenv("ADMIN_ALERT_EMAIL","").strip()

# Resolve the private-key path
if (VAPID_PRIVATE_KEY
    and not os.path.isabs(VAPID_PRIVATE_KEY)
):
    VAPID_PRIVATE_KEY = os.path.join(
        BASE_DIR,
        VAPID_PRIVATE_KEY
    )

def validate_push_configuration():
    problems = []

    if not VAPID_PUBLIC_KEY:
        problems.append(
            "VAPID_PUBLIC_KEY is missing."
        )

    if not VAPID_PRIVATE_KEY:
        problems.append(
            "VAPID_PRIVATE_KEY is missing."
        )
    elif not os.path.isfile(VAPID_PRIVATE_KEY):
        problems.append(
            "VAPID private key file was not found."
        )

    if not VAPID_SUBJECT:
        problems.append(
            "VAPID_SUBJECT is missing."
        )

    if not ADMIN_ALERT_EMAIL:
        problems.append(
            "ADMIN_ALERT_EMAIL is missing."
        )

    return problems

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
logger = logging.getLogger(__name__)

class PushSubscriptionStoreError(Exception):
    """
    Safe push-subscription storage error.
    """

    DEFAULT_MESSAGE = (
        "Unable to register this device for notifications."
    )

    def __init__(self):
        super().__init__(self.DEFAULT_MESSAGE)

class PushDeliveryError(Exception):
    """
    Safe Web Push delivery error.
    """

    DEFAULT_MESSAGE = (
        "Unable to send the notification."
    )

    def __init__(self):
        super().__init__(self.DEFAULT_MESSAGE)

class PushEndpointValidationError(Exception):
    """
    Safe Web Push endpoint validation error.
    """

    DEFAULT_MESSAGE = (
        "Invalid Web Push endpoint."
    )

    def __init__(self):
        super().__init__(
            self.DEFAULT_MESSAGE
        )

class HardenedPushSession(
    requests.Session
):
    """
    Requests session used only for outbound Web Push.
    """

    def __init__(self):
        super().__init__()

        # Prevent HTTPS_PROXY, HTTP_PROXY, NO_PROXY,
        # or other environment proxy settings from
        # silently changing the Web Push route.
        self.trust_env = False

    def request(
        self,
        method,
        url,
        **kwargs
    ):
        # A Web Push endpoint is an opaque capability URL.
        # PixelSentinel never follows a redirect to a
        # different destination.
        kwargs[
            "allow_redirects"
        ] = False

        return super().request(
            method,
            url,
            **kwargs
        )

def db_execute(query, params=(), fetch=False):
    connection = sqlite3.connect(DB_FILE)
    connection.execute("PRAGMA foreign_keys = ON")

    cursor = connection.cursor()

    try:
        cursor.execute(query, params)

        if fetch:
            return cursor.fetchall()

        connection.commit()

    except sqlite3.Error:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


def hash_invite_token(token):
    """
    Hash an enrollment token before looking it up.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

"""
Validate a PixelSentinel enrollment invitation.

  Rules:
     - Revoked invites are always rejected.
     - Unused invites must still be unexpired.
     - Used invites may still load the existing PWA when
        allow_used=True.
     - Used invites may not enroll another device when
        allow_used=False.
"""
def validate_invite(token, allow_used=False):

    if not token:
        return None

    token_hash = hash_invite_token(token)

    result = db_execute(
        """
        SELECT
            member_invites.invite_id,
            member_invites.member_id,
            member_invites.expires_at,
            member_invites.used_at,
            member_invites.revoked_at,
            members.name
        FROM member_invites
        JOIN members
            ON member_invites.member_id = members.member_id
        WHERE member_invites.token_hash = ?
        """,
        (token_hash,),
        fetch=True,
    )

    if not result:
        return None

    (
        invite_id,
        member_id,
        expires_at,
        used_at,
        revoked_at,
        member_name,
    ) = result[0]

    # Revoked links are never allowed.
    if revoked_at is not None:
        return None

    # A used link can still load the existing PWA,
    # but cannot be used to enroll another device.
    if used_at is not None:
        if not allow_used:
            return None

        return {
            "invite_id": invite_id,
            "member_id": member_id,
            "member_name": member_name,
            "expires_at": expires_at,
            "used_at": used_at,
            "used": True,
        }

    # Unused links must still be within their expiration period.
    try:
        expiration = datetime.fromisoformat(expires_at)

        if expiration.tzinfo is None:
            expiration = expiration.replace(
                tzinfo=timezone.utc
            )

        if datetime.now(timezone.utc) >= expiration:
            return None

    except (TypeError, ValueError):
        return None

    return {
        "invite_id": invite_id,
        "member_id": member_id,
        "member_name": member_name,
        "expires_at": expires_at,
        "used_at": None,
        "used": False,
    }
    
"""
 Return a friendly device label.

 Platform information is informational only and does
 not determine authorization.
"""
def get_device_label(platform):


    if platform == "ios":
        return "iPhone / iPad"

    if platform == "android":
        return "Android"

    return "Web Browser"

"""
    Validate a browser-provided Web Push endpoint
    before it is stored or contacted.

    Returns the stripped endpoint on success.

    Raises:
        PushEndpointValidationError
"""
def validate_web_push_endpoint(
    endpoint
):
    if not isinstance(
        endpoint,
        str
    ):

        raise PushEndpointValidationError()

    endpoint = endpoint.strip()

    if (
        not endpoint
        or len(endpoint) > 4096
    ):

        raise PushEndpointValidationError()

    try:

        parsed = urlparse(
            endpoint
        )

    except ValueError:

        raise PushEndpointValidationError()

    # RFC 8030 Web Push endpoints use HTTPS.
    if parsed.scheme.lower() != "https":

        raise PushEndpointValidationError()

    # Credentials must never be embedded in the URL.
    if (
        parsed.username is not None
        or parsed.password is not None
    ):

        raise PushEndpointValidationError()

    hostname = parsed.hostname

    if not hostname:

        raise PushEndpointValidationError()

    # URL fragments are never needed for a Web Push
    # delivery endpoint.
    if parsed.fragment:

        raise PushEndpointValidationError()

    try:

        port = parsed.port

    except ValueError:

        raise PushEndpointValidationError()

    if port is None:

        port = 443

    # RFC 8030 uses 443 by default and reserves
    # 1001 as the alternate Web Push service port.
    if port not in (
        443,
        1001
    ):

        raise PushEndpointValidationError()

    hostname = (
        hostname
        .rstrip(".")
        .lower()
    )

    if not hostname:

        raise PushEndpointValidationError()

    # Explicitly reject common local-only namespaces.
    local_names = (
        "localhost",
        ".localhost",
        ".local",
        ".localdomain",
        ".home.arpa",
    )

    if (
        hostname == "localhost"
        or any(
            hostname.endswith(
                suffix
            )
            for suffix
            in local_names[1:]
        )
    ):

        raise PushEndpointValidationError()

    # PixelSentinel intentionally requires a DNS
    # hostname rather than accepting a literal IP.
    #
    # Browser push providers normally issue hostname-
    # based HTTPS capability URLs, and refusing literal
    # addresses substantially reduces SSRF exposure.
    try:

        ipaddress.ip_address(
            hostname
        )

    except ValueError:

        # Not an IP literal. Continue with DNS.
        pass

    else:

        raise PushEndpointValidationError()


    # Normalize internationalized hostnames before DNS.
    try:

        dns_hostname = (
            hostname
            .encode("idna")
            .decode("ascii")
        )

    except UnicodeError:

        raise PushEndpointValidationError()

    try:

        address_info = (
            socket.getaddrinfo(
                dns_hostname,
                port,
                type=socket.SOCK_STREAM
            )
        )

    except (
        socket.gaierror,
        OSError
    ):

        raise PushEndpointValidationError()

    if not address_info:

        raise PushEndpointValidationError()

    resolved_addresses = set()

    for result in address_info:

        sockaddr = result[4]

        if not sockaddr:

            raise PushEndpointValidationError()

        address_text = (
            sockaddr[0]
            .split(
                "%",
                1
            )[0]
        )

        try:

            address = (
                ipaddress.ip_address(
                    address_text
                )
            )

        except ValueError:

            raise PushEndpointValidationError()

        resolved_addresses.add(
            address
        )

    if not resolved_addresses:

        raise PushEndpointValidationError()

    # Fail closed if even ONE DNS result points to a
    # non-public destination.
    #
    # This blocks loopback, RFC1918/private ranges,
    # link-local, multicast, unspecified, documentation
    # ranges, CGNAT/non-global space, etc.
    for address in resolved_addresses:

        if not address.is_global:

            raise PushEndpointValidationError()

    return endpoint

"""
    Create a short, non-secret identifier for log correlation.

    The actual Web Push endpoint is not written to logs.
"""    
def get_endpoint_fingerprint(endpoint):
    

    return hashlib.sha256(
        endpoint.encode("utf-8")
    ).hexdigest()[:12]

"""
    Store or refresh a Web Push subscription.

    Returns:
        The internal subscription_id on success.

    Raises:
        PushSubscriptionStoreError
"""
def save_push_subscription(
    member_id,
    subscription,
    platform,
    user_agent
):
    # member_id is expected to have been derived internally
    # from a validated invitation.
    if (
        not isinstance(member_id, int)
        or member_id <= 0
    ):
        logger.error(
            "Invalid internal member identifier passed "
            "to push subscription storage."
        )

        raise PushSubscriptionStoreError()

    # Subscription must be a dictionary.
    if not isinstance(subscription, dict):
        raise PushSubscriptionStoreError()

    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys")

    if not isinstance(keys, dict):
        raise PushSubscriptionStoreError()

    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    # Validate all required subscription fields without
    # revealing which individual value was invalid.
    required_values = (
        endpoint,
        p256dh,
        auth,
    )

    if not all(
        isinstance(value, str)
        and value.strip()
        for value in required_values
    ):
        raise PushSubscriptionStoreError()

    endpoint = endpoint.strip()
    p256dh = p256dh.strip()
    auth = auth.strip()

    # Defensive limits against oversized input.
    if (
        len(endpoint) > 4096
        or len(p256dh) > 1024
        or len(auth) > 512
    ):
        logger.warning(
            "Rejected oversized push subscription payload."
        )

        raise PushSubscriptionStoreError()

    # Validate web push endpoint
    try:
        endpoint = (validate_web_push_endpoint(endpoint))

    except PushEndpointValidationError:

        logger.warning(
            "Rejected unsafe Web Push "
            "subscription endpoint."
        )

        raise PushSubscriptionStoreError()

    # Platform is metadata only.
    # It must never be used for authorization.
    if platform not in (
        "ios",
        "android",
        "other",
    ):
        platform = "other"

    if not isinstance(user_agent, str):
        user_agent = ""

    # Prevent excessive User-Agent data from being stored.
    user_agent = user_agent[:1000]

    device_label = get_device_label(
        platform
    )

    connection = None

    try:
        connection = sqlite3.connect(
            DB_FILE,
            timeout=5
        )

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        connection.execute(
            "PRAGMA busy_timeout = 5000"
        )

        # Lock for writing so the endpoint cannot change
        # between the ownership check and the write.
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        cursor = connection.execute(
            """
            SELECT
                subscription_id,
                member_id
            FROM push_subscriptions
            WHERE endpoint = ?
            """,
            (endpoint,),
        )

        existing = cursor.fetchone()

        if existing:
            subscription_id = existing[0]
            existing_member_id = existing[1]

            # Never transfer an endpoint from one member
            # to another.
            #
            # Log only a fingerprint, not the endpoint
            # itself and not either member identity.
            if existing_member_id != member_id:
                logger.warning(
                    "Push endpoint ownership conflict. "
                    "Endpoint fingerprint: %s",
                    get_endpoint_fingerprint(
                        endpoint
                    ),
                )

                raise PushSubscriptionStoreError()

            # Same endpoint and same member.
            # Refresh keys and device metadata.
            connection.execute(
                """
                UPDATE push_subscriptions
                SET
                    p256dh = ?,
                    auth = ?,
                    platform = ?,
                    user_agent = ?,
                    device_label = ?,
                    enabled = 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE subscription_id = ?
                """,
                (
                    p256dh,
                    auth,
                    platform,
                    user_agent,
                    device_label,
                    subscription_id,
                ),
            )

        else:
            cursor = connection.execute(
                """
                INSERT INTO push_subscriptions (
                    member_id,
                    endpoint,
                    p256dh,
                    auth,
                    platform,
                    user_agent,
                    device_label
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    member_id,
                    endpoint,
                    p256dh,
                    auth,
                    platform,
                    user_agent,
                    device_label,
                ),
            )

            subscription_id = cursor.lastrowid

        connection.commit()

        return subscription_id

    except PushSubscriptionStoreError:
        if connection is not None:
            connection.rollback()

        # Already sanitized.
        raise

    except sqlite3.IntegrityError as error:
        if connection is not None:
            connection.rollback()

        # Full details stay server-side.
        logger.exception(
            "Database integrity error while "
            "storing push subscription."
        )

        raise PushSubscriptionStoreError() from error

    except sqlite3.Error as error:
        if connection is not None:
            connection.rollback()

        logger.exception(
            "SQLite error while storing "
            "push subscription."
        )

        raise PushSubscriptionStoreError() from error

    except Exception as error:
        if connection is not None:
            connection.rollback()

        logger.exception(
            "Unexpected error while storing "
            "push subscription."
        )

        raise PushSubscriptionStoreError() from error

    finally:
        if connection is not None:
            connection.close()

def build_webpush_subscription(
    endpoint,
    p256dh,
    auth
):
    """
    Convert stored PixelSentinel subscription fields into
    the format expected by pywebpush.
    """

    values = (
        endpoint,
        p256dh,
        auth,
    )

    if not all(
        isinstance(value, str)
        and value.strip()
        for value in values
    ):
        raise PushDeliveryError()

    return {
        "endpoint": endpoint.strip(),
        "keys": {
            "p256dh": p256dh.strip(),
            "auth": auth.strip(),
        }
    }
    
"""
 Send an encrypted Web Push notification.
"""
def send_web_push(
    subscription,
    payload,
    ttl=60
):
 

    if not isinstance(subscription, dict):
        raise PushDeliveryError()

    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys")

    if not isinstance(keys, dict):
        raise PushDeliveryError()

    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not all(
        isinstance(value, str)
        and value.strip()
        for value in (
            endpoint,
            p256dh,
            auth,
        )
    ):
        raise PushDeliveryError()

    if not isinstance(payload, dict):
        raise PushDeliveryError()

    # Ensure VAPID configuration is present before
    # attempting an outbound request.
    configuration_problems = (
        validate_push_configuration()
    )

    if configuration_problems:
        logger.error(
            "Web Push delivery attempted with "
            "invalid server configuration."
        )

        raise PushDeliveryError()

# Validate web push endpoint
    try:
        endpoint = (validate_web_push_endpoint(endpoint))

    except PushEndpointValidationError:

        logger.warning(
            "Blocked unsafe Web Push "
            "endpoint before delivery. "
            "Endpoint fingerprint: %s",
            get_endpoint_fingerprint(
                endpoint
            )
        )

        raise PushDeliveryError()

    try:
        with HardenedPushSession() as push_session:

            webpush(
                subscription_info=subscription,
                data=json.dumps(payload),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={
                    "sub": VAPID_SUBJECT
                },
                ttl=ttl,
                timeout=10,
                requests_session=push_session,
            )

    except WebPushException as error:

        # Only fingerprint the endpoint for log correlation.
        endpoint_fingerprint = (
            get_endpoint_fingerprint(
                endpoint
            )
        )

        status_code = None

        if getattr(error, "response", None) is not None:
            status_code = getattr(
                error.response,
                "status_code",
                None
            )

        logger.error(
            "Web Push provider rejected delivery. "
            "Endpoint fingerprint: %s, "
            "HTTP status: %s",
            endpoint_fingerprint,
            status_code or "unknown",
        )

        raise PushDeliveryError() from error

    except Exception as error:

        logger.exception(
            "Unexpected Web Push delivery failure. "
            "Endpoint fingerprint: %s",
            get_endpoint_fingerprint(
                endpoint
            ),
        )

        raise PushDeliveryError() from error

def is_valid_request_origin():
    """
    Require the subscription request to originate from the
    same HTTPS origin that served PixelSentinel.

    The Host header is supplied through the Synology
    reverse proxy.
    """

    origin = request.headers.get(
        "Origin",
        ""
    ).strip()

    if not origin:
        return False

    try:
        parsed = urlparse(origin)

    except ValueError:
        return False

    if parsed.scheme != "https":
        return False

    if parsed.netloc != request.host:
        return False

    return True
    

"""
    Record the delivery result for a Web Push
    subscription.

    Successful delivery:
        - resets failure_count
        - clears last_error
        - records last_success_at

    Failed delivery:
        - increments failure_count
        - stores only a generic safe failure code
        - preserves last_success_at

    Raw provider errors are never stored.
"""
def record_subscription_delivery_result(
    subscription_id,
    success,
    failure_code="push_send_failed"
):


    if (
        not isinstance(subscription_id, int)
        or isinstance(subscription_id, bool)
        or subscription_id < 1
    ):

        return False


    if not isinstance(
        success,
        bool
    ):

        return False
        
    allowed_failure_codes = {
        "push_send_failed",
        "test_push_failed"
    }


    if failure_code not in allowed_failure_codes:

        failure_code = (
            "push_send_failed"
        )

    connection = None

    try:

        connection = sqlite3.connect(
            DB_FILE,
            timeout=5
        )

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        connection.execute(
            "PRAGMA busy_timeout = 5000"
        )

        if success:

            cursor = connection.execute(
                '''
                UPDATE push_subscriptions

                SET
                    failure_count = 0,
                    last_error = NULL,
                    last_success_at =
                        CURRENT_TIMESTAMP,
                    admin_alert_sent_at = NULL,    
                    updated_at =
                        CURRENT_TIMESTAMP

                WHERE subscription_id = ?
                ''',
                (
                    subscription_id,
                )
            )

        else:

            cursor = connection.execute(
                '''
                UPDATE push_subscriptions

                SET
                    failure_count =
                        failure_count + 1,

                    last_error = ?,

                    updated_at =
                        CURRENT_TIMESTAMP

                WHERE subscription_id = ?
                ''',
                (
                    failure_code,
                    subscription_id
                )
            )

        if cursor.rowcount != 1:

            connection.rollback()

            return False

        connection.commit()

        return True

    except sqlite3.Error:

        if connection is not None:

            connection.rollback()

        logging.exception(
            "Database error while recording "
            "Web Push delivery result."
        )

        return False


    finally:

        if connection is not None:

            connection.close()
            
"""
    Atomically mark an unused, non-revoked invitation
    as used.

    Returns True only when an invitation was actually
    consumed.

    Database details are never exposed to the client.
"""
def consume_member_invite(invite_id):



    if (
        not isinstance(invite_id, int)
        or invite_id <= 0
    ):
        logger.error(
            "Invalid internal invite identifier passed "
            "to invite consumption."
        )

        return False

    connection = None

    try:
        connection = sqlite3.connect(
            DB_FILE,
            timeout=5
        )

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        connection.execute(
            "PRAGMA busy_timeout = 5000"
        )

        cursor = connection.execute(
            """
            UPDATE member_invites
            SET used_at = CURRENT_TIMESTAMP
            WHERE invite_id = ?
              AND used_at IS NULL
              AND revoked_at IS NULL
            RETURNING invite_id
            """,
            (invite_id,),
        )

        result = cursor.fetchone()

        if result is None:
            connection.rollback()

            logger.warning(
                "Enrollment invitation could not "
                "be consumed because no eligible "
                "invite record matched."
            )

            return False

        connection.commit()

        return True

    except sqlite3.Error:

        if connection is not None:
            connection.rollback()

        logger.exception(
            "SQLite error while consuming "
            "enrollment invitation."
        )

        return False

    finally:

        if connection is not None:
            connection.close()

@app.route(
    "/enroll/<token>/api/subscribe",
    methods=["POST"]
)
def subscribe_push(token):
    """
    Register the current browser for PixelSentinel
    Web Push notifications.

    The enrollment token determines member identity.
    The client may never supply member_id.
    """

    # Only requests from our own HTTPS origin are allowed.
    if not is_valid_request_origin():

        logger.warning(
            "Rejected push registration request "
            "with invalid Origin."
        )

        return jsonify({
            "ok": False,
            "error": "registration_failed"
        }), 403

    # Require JSON.
    if not request.is_json:
        return jsonify({
            "ok": False,
            "error": "registration_failed"
        }), 400

    data = request.get_json(
        silent=True
    )

    if not isinstance(data, dict):
        return jsonify({
            "ok": False,
            "error": "registration_failed"
        }), 400

    # Strictly allow only these top-level fields.
    #
    # In particular, member_id is NEVER accepted.
    allowed_fields = {
        "platform",
        "subscription",
    }

    if not set(data.keys()).issubset(
        allowed_fields
    ):
        logger.warning(
            "Rejected push registration request "
            "containing unexpected fields."
        )

        return jsonify({
            "ok": False,
            "error": "registration_failed"
        }), 400

    # Validate the invitation.
    #
    # Used invites cannot register another device.
    invite = validate_invite(
        token,
        allow_used=False
    )

    if invite is None:
        return jsonify({
            "ok": False,
            "error": "registration_unavailable"
        }), 403

    # member_id comes ONLY from the validated
    # server-side invite record.
    member_id = invite["member_id"]

    subscription = data.get(
        "subscription"
    )

    platform = data.get(
        "platform",
        "other"
    )

    # Platform is metadata only.
    if platform not in (
        "ios",
        "android",
        "other",
    ):
        platform = "other"

    user_agent = request.headers.get(
        "User-Agent",
        ""
    )

    try:
        subscription_id = (
            save_push_subscription(
                member_id=member_id,
                subscription=subscription,
                platform=platform,
                user_agent=user_agent,
            )
        )

    except PushSubscriptionStoreError:

        # The storage layer has already reduced the
        # failure to a safe generic condition.
        return jsonify({
            "ok": False,
            "error": "registration_failed"
        }), 400

    # We now have a stored subscription.
    # Send the enrollment test notification.
    try:
        send_test_push(
            subscription
        )

    except PushDeliveryError:

        try:
            record_subscription_delivery_result(
                subscription_id,
                success=False,
                failure_code="test_push_failed"
            )

        except Exception:
            # Already logged server-side.
            pass

        # Do NOT consume the invitation.
        #
        # The user can retry after the problem
        # has been corrected.
        return jsonify({
            "ok": False,
            "error": "registration_failed"
        }), 503

    # Test push succeeded.
    try:
        record_subscription_delivery_result(
            subscription_id,
            success=True
        )

    except Exception:

        # A successful real push happened, but we could
        # not safely record its state. Do not claim full
        # registration success.
        logger.error(
            "Test push succeeded but delivery status "
            "could not be recorded."
        )

        return jsonify({
            "ok": False,
            "error": "registration_failed"
        }), 500

    # Consume the invite only after:
    #
    #   subscription saved
    #   AND
    #   test push succeeded
    #   AND
    #   success state recorded
    invite_consumed = consume_member_invite(
        invite["invite_id"]
    )

    if not invite_consumed:

        logger.error(
            "Push registration succeeded but "
            "the enrollment invitation could "
            "not be consumed."
        )

        return jsonify({
            "ok": False,
            "error": "registration_failed"
        }), 409

    return jsonify({
        "ok": True
    }), 200
    
def send_test_push(subscription):
    """
    Send the enrollment verification notification.
    """

    payload = {
        "title": "PixelSentinel Alerts",
        "body": (
            "Test successful. "
            "Photo alerts are ready."
        ),
        "type": "enrollment_test"
    }

    send_web_push(
        subscription=subscription,
        payload=payload,
        ttl=60,
    )

def is_valid_removal_request_origin():
    """
    Require the removal acknowledgement to come from
    PixelSentinel's own HTTPS origin.
    """

    origin = request.headers.get(
        "Origin"
    )

    if not origin:

        return False


    try:

        parsed_origin = urlparse(
            origin
        )

    except ValueError:

        return False


    if parsed_origin.scheme != "https":

        return False


    if parsed_origin.netloc != request.host:

        return False


    return True

def acknowledge_subscription_removal(
    removal_token
):
    """
    Complete a remotely acknowledged push-subscription
    removal.
    """

    if not isinstance(
        removal_token,
        str
    ):

        return False


    removal_token = removal_token.strip()


    if (
        not removal_token
        or len(removal_token) > 256
    ):

        return False


    token_hash = hashlib.sha256(
        removal_token.encode(
            "utf-8"
        )
    ).hexdigest()


    connection = None


    try:

        connection = sqlite3.connect(
            DB_FILE,
            timeout=5
        )

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        connection.execute(
            "PRAGMA busy_timeout = 5000"
        )

        connection.execute(
            "BEGIN IMMEDIATE"
        )


        removal = connection.execute(
            '''
            SELECT
                removal_id,
                subscription_id

            FROM subscription_removals

            WHERE token_hash = ?

              AND datetime(
                    expires_at
                  ) > CURRENT_TIMESTAMP

            LIMIT 1
            ''',
            (
                token_hash,
            )
        ).fetchone()


        if removal is None:

            connection.rollback()

            return False


        removal_id = removal[0]
        subscription_id = removal[1]


        cursor = connection.execute(
            '''
            DELETE FROM push_subscriptions

            WHERE subscription_id = ?
            ''',
            (
                subscription_id,
            )
        )


        if cursor.rowcount != 1:

            connection.rollback()

            return False


        connection.commit()


        logging.info(
            "Push subscription removal "
            "acknowledged: removal_id=%s "
            "subscription_id=%s",
            removal_id,
            subscription_id
        )


        return True


    except sqlite3.Error:

        if connection is not None:

            connection.rollback()


        logging.exception(
            "Database error while acknowledging "
            "push subscription removal."
        )


        return False


    finally:

        if connection is not None:

            connection.close()
    
@app.route("/")
def index():
    """
    PixelSentinel intentionally has no public home page.
    """
    abort(404)


@app.route("/enroll/<token>")
def enroll(token):
    invite = validate_invite(
        token,
        allow_used=True
    )

    if invite is None:
        return render_template(
            "enrollment_error.html"
        ), 403

    return render_template(
        "enroll.html",
        member_name=invite["member_name"],
        token=token,
        invite_used=invite["used"],
    )

@app.route("/enroll/<token>/manifest.webmanifest")
def enrollment_manifest(token):
    invite = validate_invite(
        token,
        allow_used=True
    )

    if invite is None:
        abort(404)

    manifest = {
        "id": f"/pixelsentinel-alerts/member/{invite['member_id']}",
        "name": "PixelSentinel Alerts",
        "short_name": "PixelSentinel",
        "start_url": url_for("enroll", token=token),
        "scope": "/",
        "display": "standalone",
        "background_color": "#111827",
        "theme_color": "#111827",
        "icons": [
            {
                "src": "/static/icons/icon-192.png",
                "sizes": "192x192",
                "type": "image/png"
            },
            {
                "src": "/static/icons/icon-512.png",
                "sizes": "512x512",
                "type": "image/png"
            }
        ]
    }

    response = make_response(jsonify(manifest))
    response.headers["Content-Type"] = (
        "application/manifest+json"
    )
    response.headers["Cache-Control"] = "no-store"

    return response

@app.errorhandler(404)
def not_found(error):
    return "", 404
    
@app.errorhandler(413)
def request_too_large(error):
    return jsonify({
        "ok": False,
        "error": "registration_failed"
    }), 413

@app.after_request
def secure_responses(response):
    """
    Prevent private enrollment URLs and push removal
    responses from being cached or leaked through
    referrer headers.
    """

    protected_response = (
        request.path.startswith(
            "/enroll/"
        )
        or request.path == "/api/removal/ack"
    )

    if protected_response:

        response.headers[
            "Cache-Control"
        ] = (
            "no-store, no-cache, must-revalidate, "
            "max-age=0"
        )

        response.headers[
            "Pragma"
        ] = "no-cache"

        response.headers[
            "Referrer-Policy"
        ] = "no-referrer"

        response.headers[
            "X-Content-Type-Options"
        ] = "nosniff"

        response.headers[
            "X-Frame-Options"
        ] = "DENY"

    return response

@app.route(
    "/enroll/<token>/api/vapid-public-key",
    methods=["GET"]
)
def vapid_public_key(token):
    """
    Return the PixelSentinel VAPID public key to a
    browser associated with a valid enrollment link.

    The VAPID private key is never exposed.
    """

    invite = validate_invite(
        token,
        allow_used=True
    )

    if invite is None:
        abort(404)

    if not VAPID_PUBLIC_KEY:
        logger.error(
            "VAPID public key requested but "
            "server configuration is unavailable."
        )

        return jsonify({
            "ok": False,
            "error": "service_unavailable"
        }), 503

    return jsonify({
        "ok": True,
        "public_key": VAPID_PUBLIC_KEY
    }), 200

@app.post(
    "/api/removal/ack"
)
def acknowledge_push_removal():
    """
    Receive confirmation that a browser has successfully
    unsubscribed from its remote push service.
    """

    if not is_valid_removal_request_origin():

        return {
            "ok": False
        }, 403

    data = request.get_json(
        silent=True
    )

    if not isinstance(
        data,
        dict
    ):

        return {
            "ok": False
        }, 400

    allowed_fields = {
        "removal_token"
    }

    if set(
        data.keys()
    ) != allowed_fields:

        return {
            "ok": False
        }, 400

    removal_token = data.get(
        "removal_token"
    )

    if (
        not isinstance(
            removal_token,
            str
        )
        or not removal_token.strip()
        or len(removal_token) > 256
    ):

        return {
            "ok": False
        }, 400


    removed = (
        acknowledge_subscription_removal(
            removal_token
        )
    )


    if not removed:

        return {
            "ok": False
        }, 404


    return {
        "ok": True
    }, 200

@app.route("/service-worker.js")
def service_worker():
    response = make_response(
        send_from_directory(
            os.path.join(BASE_DIR, "static"),
            "service-worker.js"
        )
    )

    response.headers["Content-Type"] = (
        "application/javascript"
    )

    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"

    return response

if __name__ == "__main__":

    configuration_problems = (
        validate_push_configuration()
    )

    if configuration_problems:

        print(
            "\nPixelSentinel Web Push "
            "configuration problems:"
        )

        for problem in configuration_problems:
            print(f" - {problem}")

        print()

    else:

        print(
            "\nPixelSentinel Web Push "
            "configuration: OK"
        )

        print(
            "VAPID private key: FOUND"
        )

        print(
            "VAPID public key: SET"
        )

        print(
            "VAPID subject: SET"
        )

        print(
            "Administrator alert email: SET\n"
        )

    app.run(
        host="127.0.0.1",
        port=5055,
        debug=False,
    )