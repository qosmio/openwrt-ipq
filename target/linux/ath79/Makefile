include $(TOPDIR)/rules.mk

ARCH:=mips
BOARD:=ath79
BOARDNAME:=Atheros ATH79
CPU_TYPE:=24kc
SUBTARGETS:=generic mikrotik nand tiny

FEATURES:=ramdisk squashfs usbgadget

KERNEL_PATCHVER:=6.6
KERNEL_TESTING_PATCHVER:=6.12

include $(INCLUDE_DIR)/target.mk

DEFAULT_PACKAGES += \
	kmod-gpio-button-hotplug swconfig \
	kmod-ath9k uboot-envtools

$(eval $(call BuildTarget))
