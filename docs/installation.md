# Installation guide

Evok can be installed on Unipi OS or RaspberryPi OS based on Debian 13 Trixie, Evok 3.1 needs Python 3.12 or newer.
To install Evok, you will have to [prepare the OS](#os-preparation) and then [install the package](#installing-and-updating-evok),
or install it [into a virtual environment](#installing-into-a-virtual-environment).

## OS preparation

This step varies by the platform used, either [Unipi images](#pre-built-unipi-os-images) or [RaspberryPi OS](#raspberrypi-os).

### Pre-built Unipi OS images

The latest images for Unipi controllers, including those with Evok pre-installed, can be downloaded from the [Unipi Technology Knowledge Base](https://kb.unipi.technology/os-images).

All necessary APT Unipi repositories are already preconfigured in the OS images. Therefore, all that's required is to login to the controller via SSH. The default username for our images is "unipi" and the default password is "unipi.technology".

You can proceed to [Installing and updating Evok](#installing-and-updating-evok) section.

### RaspberryPi OS

In order to install Evok on Neuron/Unipi1.X with RaspberryPi OS, you will need an SD card with a standard (Lite) RaspberryPi OS. We recommend enabling SSH via [RaspberryPi OS imager](https://www.raspberrypi.com/software/).

To add Evok repositories and install required modules, connect to your controller using SSH. The username and password for Raspberry Pi OS are set using the Raspberry Pi OS Imager. After you connect to your controller execute the following commands:

#### Neuron

```bash
sudo su
wget -qO - https://repo.unipi.technology/debian/raspberry-neuron.sh | bash
reboot
```

#### Unipi 1.X

```bash
sudo su
wget -qO - https://repo.unipi.technology/debian/raspberry-unipi1.sh | bash
reboot
```

You can proceed to [Installing and updating Evok](#installing-and-updating-evok) section.

## Installing and updating Evok

Make sure you have [prepared the OS](#os-preparation) correctly first. Following steps work both for installing and updating

```bash title="Installing & updating Evok"
sudo apt update
sudo apt install -y evok
```

> **Tip**
> 
> If you wish, you can also install or update Evok-web.

```bash title="Installing & updating Evok-web"
sudo apt install -y evok-web
```

## Installing into a virtual environment

Evok can be installed by pip into a Python virtual environment without its Debian package, e.g. to try
a development branch. It needs Python 3.12 or newer (Debian 13 Trixie).

> **Note**
> 
> The Debian package `evok` must not run at the same time, both use the port 8080:
> `sudo systemctl disable --now evok`.

```bash title="Installing Evok into ~/evok"
sudo apt install -y python3-venv git
python3 -m venv ~/evok/venv
~/evok/venv/bin/pip install "git+https://github.com/UnipiTechnology/evok@dev-3.1"
```

The same command with `--upgrade` updates Evok, a branch, a tag or a commit can follow `@`.

The configuration directory contains `config.yaml` and `hw_definitions/`
(see [configuration](./configs/evok_configuration.md)). With `autogen: true` it also needs `autogen.yaml`,
which the Unipi OS generates to `/etc/evok/autogen.yaml`; without it the buses are configured in `comm_channels`
of `config.yaml`.

```bash title="Preparing the configuration"
EVOK_VER=dev-3.1
mkdir -p ~/evok/etc
curl -o ~/evok/etc/config.yaml https://raw.githubusercontent.com/UnipiTechnology/evok/$EVOK_VER/examples/config.yaml
mkdir -p ~/evok/etc/hw_definitions
curl -sL https://github.com/UnipiTechnology/evok/archive/$EVOK_VER.tar.gz \
  | tar xz -C ~/evok/etc/hw_definitions --strip-components=3 --wildcards '*/hw_definitions/*/*.yaml'
ln -s /etc/evok/autogen.yaml ~/evok/etc/autogen.yaml
```

```bash title="Running Evok"
~/evok/venv/bin/evok --config-dir ~/evok/etc --alias-file ~/evok/alias.yaml
```

The user running Evok needs the access to the serial ports of the Modbus RTU buses (the group `dialout`)
and to the 1-Wire bus (the group `evok` of the [udev rule](#1-wire-bus)). Evok can be started by systemd,
e.g. with `/etc/systemd/system/evok-venv.service` for the user `unipi`:

```ini title="evok-venv.service"
[Unit]
Description=Evok in a virtual environment
After=network.target

[Service]
User=unipi
ExecStart=/home/unipi/evok/venv/bin/evok --config-dir /home/unipi/evok/etc --alias-file /home/unipi/evok/alias.yaml
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash title="Enabling the service"
sudo systemctl daemon-reload
sudo systemctl enable --now evok-venv
```

## 1-Wire bus

Evok 3.1 reads the 1-Wire sensors by the kernel, owserver is not needed. The 1-Wire master (e.g. the DS2482)
and the modules of the sensors (`w1_therm` and others) have to be loaded by the kernel. The udev rule
[`60-evok-w1.rules`](https://github.com/UnipiTechnology/evok/blob/dev-3.1/etc/udev/rules.d/60-evok-w1.rules)
gives Evok the access to the forced search and to the conversion of all thermometers at once:

```bash title="Installing the udev rule"
sudo cp 60-evok-w1.rules /etc/udev/rules.d/
sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=w1 --action=add
```

See [OWFS bus](./configs/evok_configuration.md#bus-configuration) in the configuration.

## Uninstallation

```bash title="Uninstalling Evok"
sudo apt remove evok evok-web
reboot
```

> **Note**
> 
> After uninstalling Evok, you have to reboot your device to ensure all the files and settings are gone.

----

Raspberry Pi is a trademark of the Raspberry Pi Foundation
