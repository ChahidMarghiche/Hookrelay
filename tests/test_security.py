from app import security


def test_sign_verify_roundtrip():
    secret, body = "s3cret", b'{"hello":"world"}'
    sig = security.sign(secret, body)
    assert security.verify(secret, body, sig) is True


def test_verify_rejects_wrong_signature():
    body = b"payload"
    assert security.verify("secret", body, "deadbeef") is False


def test_verify_rejects_missing_signature():
    assert security.verify("secret", b"payload", None) is False


def test_verify_rejects_tampered_body():
    secret = "secret"
    sig = security.sign(secret, b"original")
    assert security.verify(secret, b"tampered", sig) is False
