from cryptography.fernet import Fernet

# This key must be the same on client and server
SECRET_KEY = b'YOUR-SECRET-KEY-HERE=='
cipher = Fernet(SECRET_KEY)


def encrypt_data(data: str) -> str:
    encoded = data.encode()
    encrypted = cipher.encrypt(encoded)
    return encrypted.decode()


def decrypt_data(data: str) -> str:
    decrypted = cipher.decrypt(data.encode())
    return decrypted.decode()
