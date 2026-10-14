# Installation guide

Evok can be installed on Unipi OS or RaspberryPi OS based on Debian 13 Trixie, Evok 3.1 needs Python 3.12 or newer.
To install Evok, you will have to [prepare the OS](#os-preparation) and then [install the package](#installing-and-updating-evok).

## OS preparation

This step varies by the platform used, either [Unipi images](#pre-built-unipi-os-images) or [RaspberryPi OS](#raspberrypi-os).

### Pre-built Unipi OS images

The latest images for Unipi controllers, including those with Evok pre-installed, can be downloaded from the [Unipi Technology Knowledge Base](https://kb.unipi.technology/os-images).

All necessary APT Unipi repositories are already preconfigured in the OS images. Therefore, all that's required is to login to the controller via SSH. The default username for our images is "unipi" and the default password is "unipi.technology".

You can proceed to [Installing and updating Evok](#installing-and-updating-evok) section.

### RaspberryPi OS

In order to install Evok on Neuron/Unipi1.X with RaspberryPi OS, you will need an SD card with a standard (Lite) RaspberryPi OS. We recommend enabling SSH via [RaspberryPi OS imager](https://www.raspberrypi.com/software/).

To add Evok repositories and install required modules, connect to your controller using SSH. The username and password for Raspberry Pi OS are set using the Raspberry Pi OS Imager. After you connect to your controller execute the following commands:

=== "For Neuron"

    ```bash
    sudo su
    wget -qO - https://repo.unipi.technology/debian/raspberry-neuron.sh | bash
    reboot
    ```

=== "For Unipi1.X"

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

!!! tip
    If you wish, you can also install or update Evok-web.

    ```bash title="Installing & updating Evok-web"
    sudo apt install -y evok-web
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

!!! note

    After uninstalling Evok, you have to reboot your device to ensure all the files and settings are gone.

----

Raspberry Pi is a trademark of the Raspberry Pi Foundation
