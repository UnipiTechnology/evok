# Installation guide

Evok can be installed on Unipi OS or RaspberryPi OS.
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

## Beta version

!!! danger
    Do not use in production environment, use solely for development.
    Beta version includes new features.
    These features may change or be removed during development.

There are several ways of getting beta version.

### Switching to the beta repository

**To be able use the beta version, you need to have the [OS prepared](#os-preparation) already**. You can switch to the beta version of Evok by adding the repository to the apt sources:

=== "Neuron"

    ```bash
    echo "deb https://repo.unipi.technology/debian betaevok:bookworm main neuron-main neuron-test test" >> /etc/apt/sources.list.d/unipi.list
    apt update
    ```

=== "Patron"

    ```bash
    echo "deb https://repo.unipi.technology/debian betaevok:bookworm main patron-main patron-test test" >> /etc/apt/sources.list.d/unipi.list
    apt update
    ```

=== "Gate"

    ```bash
    echo "deb https://repo.unipi.technology/debian betaevok:bookworm main g1-main g1-test test" >> /etc/apt/sources.list.d/unipi.list
    apt update
    ```

=== "Unipi 1.1"

    ```bash
    echo "deb https://repo.unipi.technology/debian betaevok:bookworm main unipi1-main unipi1-test test" >> /etc/apt/sources.list.d/unipi.list
    apt update
    ```

You can proceed to [Installing and updating Evok](#installing-and-updating-evok) section.

## Uninstallation

```bash title="Uninstalling Evok"
sudo apt remove evok evok-web
reboot
```

!!! note

    After uninstalling Evok, you have to reboot your device to ensure all the files and settings are gone.

----

Raspberry Pi is a trademark of the Raspberry Pi Foundation
