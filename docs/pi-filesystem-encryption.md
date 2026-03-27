# Raspberry Pi Filesystem Encryption Options

This document covers encryption options for the Pi running cryptotrader. The main
challenge is that the Pi must auto-recover after power cuts with no manual intervention,
which conflicts with passphrase-based full-disk encryption.

---

## Option 1 — LUKS Full-Disk Encryption

Encrypts the entire root partition. Standard Linux approach using `cryptsetup`.

**How it works:** On every boot the Pi halts at an initramfs prompt waiting for a
passphrase before the root filesystem mounts.

**Problem for a headless always-on device:** Without a passphrase the Pi never finishes
booting. This requires remote unlock via SSH (Dropbear in initramfs).

### Remote unlock setup (Dropbear)

```bash
sudo apt install cryptsetup dropbear-initramfs

# Add your SSH public key so you can unlock remotely
sudo nano /etc/dropbear/initramfs/authorized_keys

# Rebuild initramfs
sudo update-initramfs -u

# On every reboot, SSH in to unlock:
ssh -p 2222 root@192.168.1.66
# Enter LUKS passphrase at the prompt
```

**Trade-off:** If the home network is down during a reboot (power cut, ISP outage),
the Pi never comes back. Pi-hole DNS stops working, and the trading bot stays offline
until you physically or remotely unlock it.

---

## Option 2 — LUKS with Auto-Unlock via Key File

Stores the LUKS passphrase in a key file on the unencrypted `/boot` partition. The root
partition unlocks automatically on every boot without any manual step.

```bash
# Generate a key file
sudo dd if=/dev/urandom of=/boot/luks.key bs=512 count=1
sudo chmod 400 /boot/luks.key

# Add the key file as a LUKS slot
sudo cryptsetup luksAddKey /dev/mmcblk0p2 /boot/luks.key

# Configure crypttab to use it
echo "cryptroot /dev/mmcblk0p2 /boot/luks.key luks" | sudo tee -a /etc/crypttab
```

**What it protects against:** Someone stealing only the SD card can't read the root
partition without the key file — which is on the boot partition of the same card.
Effectively the same as no encryption if they take the whole SD card.

**What it actually protects against:** Physical theft of the Pi *without* the SD card
(e.g. someone removes and clones the card while the Pi is running and the card is
mounted read-only). Niche threat.

**Trade-off:** Auto-unlocks on every boot — no reboot risk. But the key is on the same
physical device so protection is limited.

---

## Option 3 — Encrypt Sensitive Files Only (Recommended)

Rather than full-disk encryption, encrypt only the files that contain secrets:
`.env` (Kraken API keys) and `cryptotrader.db` (trade history with transaction IDs).

This avoids all reboot complexity while protecting the highest-value data.

### Using `age` for the .env file

```bash
# Install age
sudo apt install age

# Generate a key pair (store the private key securely off-device)
age-keygen -o ~/.age-key.txt

# Encrypt the .env file
age -e -r <public-key-from-age-keygen> /opt/cryptotrader/.env \
    > /opt/cryptotrader/.env.age

# Decrypt at service start (add to a wrapper script)
age -d -i ~/.age-key.txt /opt/cryptotrader/.env.age > /tmp/cryptotrader.env
```

The systemd service would reference the decrypted tmpfs copy:
```ini
EnvironmentFile=-/tmp/cryptotrader.env
```

### Using fscrypt (directory-level encryption)

`fscrypt` encrypts at the filesystem level using a passphrase or PAM integration.
Works well for protecting `/opt/cryptotrader` as a whole.

```bash
sudo apt install fscrypt
sudo fscrypt setup
sudo fscrypt encrypt /opt/cryptotrader
```

---

## Option 4 — TPM-Backed Auto-Unlock (Pi 5 only)

The Raspberry Pi 5 includes a dedicated security chip (RP1). Tools like `clevis` can
bind a LUKS volume to the TPM so the Pi unlocks automatically on its own hardware but
the key is never accessible from the SD card alone.

```bash
sudo apt install clevis clevis-luks clevis-tpm2
sudo clevis luks bind -d /dev/mmcblk0p2 tpm2 '{}'
```

**Trade-off:** Requires Pi 5. Provides genuine full-disk encryption with auto-boot.
If the TPM is cleared or the hardware is changed, the drive is unreadable.

---

## Practical Recommendation

For this setup (Pi-hole + always-on trading bot, must auto-recover after power cuts):

| Threat | Best mitigation |
|---|---|
| Someone steals SD card only | Option 2 (LUKS + key file on boot partition) |
| Someone steals entire Pi | None practical without Option 1 + Dropbear |
| API keys exposed if Pi is compromised | Kraken IP whitelist + key rotation |
| Trade history exposed | Option 3 (encrypt `cryptotrader.db`) |

**Minimum recommended steps regardless of encryption choice:**

1. Enable Kraken's API key IP whitelist to your home IP — most effective single control
2. Ensure `.env` is `chmod 600` and owned by `peterk` (already enforced by Ansible)
3. Rotate Kraken API keys after any suspected compromise
4. Keep `cryptotrader.db` permissions at `600` (see security issue #9)
