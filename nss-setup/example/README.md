# **Overview**

Below are few examples of how to setup additional services with NSS.
# **Table of Contents**

* [VLAN](#vlan)
  * [<strong>VLAN Tagging (8021q)</strong>](#vlan-tagging-8021q)
     - [<strong>Example VLAN Setup</strong>](#example-vlan-setup)
* [WWAN](#wwan)
     - [<strong>Example WWAN Setup</strong>](#example-vlan-setup)

---

## VLAN

**Important Note:**

To setup VLANs you must use `8021q` tagging, since `bridge VLAN filtering` is **NOT compatible with NSS WiFi**. That means your config should NOT contain any syntax that uses `option vlan_filtering 1`, `config bridge-vlan` or port tagging `list ports 'lan1:u*'`.

---

**Check if VLAN Filtering is Enabled**

Run the following command to check if VLAN filtering is active:
```vim
uci show network | grep vlan_filtering
```

If you see a line like this:

```vim
network.@device[0].vlan_filtering='1'
```

VLAN filtering is enabled and you **must disable it**.

To disable VLAN filtering, run:
```vim
uci del 'network.@device[0].vlan_filtering'
uci commit network
service network restart
```

### **VLAN Tagging (8021q)**

Instead of tagging, you'll need to follow a different approach.

1. **Set up VLANs on specific ports.**
2. **Bridge these VLANs into interfaces** (you can leave them **unmanaged** if needed).
3. **Create firewall rules** to manage traffic between VLANs.

---

#### **Example VLAN Setup**

- A **Primary Network** on VLAN 1 (untagged).
- A **Guest Network** on VLAN 30.
- An **IoT Network** on VLAN 40.

**UCI Config**

`/etc/config/network`:

```vim
config interface 'loopback'
    option device 'lo'
    option proto 'static'
    option ipaddr '127.0.0.1'
    option netmask '255.0.0.0'

config globals 'globals'
    option ula_prefix 'fd32:aa0c:9a35::/48'

config device
    option name 'br-lan'
    option type 'bridge'
    list ports 'lan1'
    list ports 'lan2'
    list ports 'lan3'
    list ports 'lan4'
    option igmp_snooping '1'

config interface 'lan'
    option device 'br-lan'
    option proto 'static'
    list ipaddr '192.168.1.1/24'

config device
    option type 'bridge'
    option name 'br-iot'
    list ports 'lan1.40'
    list ports 'lan2.40'

config device
    option type 'bridge'
    option name 'br-guest'
    list ports 'lan1.30'
    list ports 'lan3.30'

config interface 'guest'
    option proto 'none'
    option device 'br-guest'

config interface 'iot'
    option proto 'none'
    option device 'br-iot'
```

`/etc/config/wireless`:

```vim
config wifi-iface 'lan'
    option device 'radio0'
    option mode 'ap'
    option network 'lan'
    option ssid 'OpenWrt'
    option encryption 'psk2+ccmp'
    option key '********'

config wifi-iface 'guest'
    option device 'radio0'
    option mode 'ap'
    option network 'guest'
    option ssid 'OpenWrt-Guest'
    option encryption 'psk2+ccmp'
    option key '********'

config wifi-iface 'iot'
    option device 'radio0'
    option mode 'ap'
    option network 'iot'
    option ssid 'OpenWrt-IoT'
    option encryption 'psk2+ccmp'
    option key '********'
```

`/etc/config/firewall`:

```vim
config zone
    option name 'guest'
    option input 'ACCEPT'
    option output 'ACCEPT'
    option forward 'REJECT'
    list network 'guest'

config forwarding
    option src 'guest'
    option dest 'wan'

config zone
    option name 'iot'
    option input 'ACCEPT'
    option output 'ACCEPT'
    option forward 'REJECT'
    list network 'iot'

config forwarding
    option src 'iot'
    option dest 'wan'

# To allow communication from lan->guest and iot

config forwarding
    option src 'lan'
    option dest 'guest'

config forwarding
    option src 'lan'
    option dest 'iot'
```
---

## WWAN

IMPORTANT: The `nss-packages` repository does not provide support for `wwan` in the default branch `NSS-12.5-K6.x`. Support for it was removed and moved into an unsupported branch [NSS-12.5-K6.x-wwan](https://github.com/qosmio/nss-packages/tree/NSS-12.5-K6.x-wwan). Please note, any issues opened with these packages will be closed.

To properly set up WWAN (`Arcadyan AW1000`), you need to create the following 3 interfaces:

- **wwan** - Primary interface for the modem connection. (`proto quectel`)
- **wwan_4** - Interface IPv4 connections. (`proto dhcp`)
- **wwan_6** - Handle IPv6 connections. (`proto dhcpv6`)

#### **Example WWAN Setup**

**UCI Config**

`/etc/config/network`:

```vim
config interface 'wwan'
    option proto 'quectel'
    option auth 'none'
    option delay '5'
    option mtu '1500'
    option pdptype 'ipv4v6'
    option device '/dev/cdc-wdm0'
    option apn 'internet'
    # Cloudflare DNS servers
    list dns '1.1.1.1'
    list dns '1.0.0.1'

config interface 'wwan_4'
    option proto 'dhcp'
    option peerdns '1'
    option defaultroute '1'
    option metric '10'
    option device 'wwan0_1'

config interface 'wwan_6'
    option proto 'dhcpv6'
    option reqaddress 'try'
    option reqprefix 'auto'
    option peerdns '1'
    option defaultroute '1'
    option metric '20'
    option device 'wwan0_1'
```

`/etc/config/firewall`:

```vim
config zone
    option name 'wan'
    list network 'wwan'
    list network 'wwan_4'
    list network 'wwan_6'
    option input 'REJECT'
    option output 'ACCEPT'
    option forward 'REJECT'
    option masq '1'
    option mtu_fix '1'
```

