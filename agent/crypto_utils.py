from cryptography.fernet import Fernet


def generate_key() -> str:
    return Fernet.generate_key().decode()


def encrypt_key(private_key: bytes, encryption_key: str) -> str:
    f = Fernet(encryption_key.encode())
    return f.encrypt(private_key).decode()


def decrypt_key(encrypted: str, encryption_key: str) -> bytes:
    f = Fernet(encryption_key.encode())
    return f.decrypt(encrypted.encode())
