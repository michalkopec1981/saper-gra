import qrcode
import os

# Tworzymy folder qrcodes, jeśli nie istnieje
if not os.path.exists('qrcodes'):
    os.makedirs('qrcodes')

# Generujemy 10 zwykłych kodów QR
for i in range(1, 11):
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(f'qr{i}')
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(f'qrcodes/qr{i}.png')

# Generujemy 2 specjalne kody QR
for i in range(1, 3):
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(f'special{i}')
    qr.make(fit=True)
    img = qr.make_image(fill_color="blue", back_color="white")
    img.save(f'qrcodes/special{i}.png')

# Generujemy czerwoną bombę
qr = qrcode.QRCode(version=1, box_size=10, border=5)
qr.add_data('red_bomb')
qr.make(fit=True)
img = qr.make_image(fill_color="red", back_color="white")
img.save('qrcodes/red_bomb.png')

print("Wygenerowano kody QR w folderze 'qrcodes'")