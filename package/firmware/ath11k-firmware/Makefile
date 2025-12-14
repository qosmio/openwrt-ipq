#
# Copyright (C) 2022 OpenWrt.org
#
# This is free software, licensed under the GNU General Public License v2.
# See /LICENSE for more information.
#

include $(TOPDIR)/rules.mk

PKG_NAME:=ath11k-firmware
PKG_VERSION_REAL:=2.12-01460
PKG_VERSION:=2025.12.17
PKG_SOURCE:=$(PKG_NAME)-$(PKG_VERSION_REAL).tar.zst
PKG_SOURCE_URL:=https://github.com/qosmio/upstream-wifi-fw/releases/download/$(PKG_VERSION_REAL)
PKG_HASH:=a2767b367a51e15c1ab4d303113a0d1e22e73adf727a418119f4509f0ef115dd
PKG_RELEASE:=1
PKG_BUILD_DIR:=$(BUILD_DIR)/$(PKG_NAME)-$(subst -,.,$(PKG_VERSION_REAL))

PKG_LICENSE_FILES:=LICENSE.qca_firmware

PKG_MAINTAINER:=Robert Marko <robimarko@gmail.com>

include $(INCLUDE_DIR)/package.mk

RSTRIP:=:
STRIP:=:

ATH11K_LEGACY_FW_NAME:=ath11k-legacy-firmware
ATH11K_LEGACY_FW_DATE:=2024-03-14
ATH11K_LEGACY_FW_RELEASE:=795809c7
ATH11K_LEGACY_FW_SUBDIR:=$(ATH11K_LEGACY_FW_NAME)-$(ATH11K_LEGACY_FW_DATE)~$(ATH11K_LEGACY_FW_RELEASE)
ATH11K_LEGACY_FW_SOURCE=$(ATH11K_LEGACY_FW_SUBDIR).tar.zst

define Download/$(ATH11K_LEGACY_FW_NAME)
	FILE:=$(ATH11K_LEGACY_FW_SOURCE)
	PROTO:=git
	URL:=https://github.com/quic/upstream-wifi-fw.git
	SOURCE_VERSION:=795809c7041582bd51bdfaa1f548b916ae8d4382
	MIRROR_HASH:=b55bf7204543c7ba87876e84788239b0e47ad62434c5b0d1169526cde36a9daa
	SUBDIR:=$(ATH11K_LEGACY_FW_SUBDIR)
endef

define Package/ath11k-firmware-default
  SECTION:=firmware
  CATEGORY:=Firmware
  URL:=$(PKG_SOURCE_URL)
  DEPENDS:=
endef

define Package/ath11k-firmware-ipq5018
$(Package/ath11k-firmware-default)
  TITLE:=IPQ5018 ath11k firmware
endef

define Package/ath11k-firmware-ipq5018-qcn6122
$(Package/ath11k-firmware-default)
  TITLE:=IPQ5018/QCN6122 ath11k firmware
endef

define Package/ath11k-firmware-ipq6018
$(Package/ath11k-firmware-default)
  TITLE:=IPQ6018 ath11k firmware
endef

define Package/ath11k-firmware-ipq8074
$(Package/ath11k-firmware-default)
  TITLE:=IPQ8074 ath11k firmware
endef

define Package/ath11k-firmware-qcn9074
$(Package/ath11k-firmware-default)
  TITLE:=QCN9074 ath11k firmware
endef

define Build/Clean
	$(call Build/Clean/Default,)

	rm -rf \
		$(BUILD_DIR)/$(ATH11K_LEGACY_FW_SUBDIR)
endef

ifneq ($(CONFIG_PACKAGE_ath11k-firmware-ipq5018-qcn6122),)
$(eval $(call Download,ath11k-legacy-firmware))
endif

define Build/Prepare
	$(call Build/Prepare/Default,)

ifneq ($(CONFIG_PACKAGE_ath11k-firmware-ipq5018-qcn6122),)
	$(TAR) -C $(BUILD_DIR) -xf $(DL_DIR)/$(ATH11K_LEGACY_FW_SOURCE)
endif
endef

define Build/Compile

endef

define Package/ath11k-firmware-ipq5018/install
	$(INSTALL_DIR) $(1)/lib/firmware/ath11k/IPQ5018/hw1.0
	$(INSTALL_DATA) \
		$(PKG_BUILD_DIR)/IPQ5018_QCN6122/hw1.0/testing/2.12/WLAN.HK.2.12-01460-QCAHKSWPL_SILICONZ-1/* \
		$(1)/lib/firmware/ath11k/IPQ5018/hw1.0/
endef

define Package/ath11k-firmware-ipq5018-qcn6122/install
	$(INSTALL_DIR) $(1)/lib/firmware/ath11k/IPQ5018/hw1.0
	$(INSTALL_DATA) \
		$(BUILD_DIR)/$(ATH11K_LEGACY_FW_SUBDIR)/ath11k-firmware/IPQ5018_QCN6122_QCN6122/hw1.0/2.7.0.1/WLAN.HK.2.7.0.1-01744-QCAHKSWPL_SILICONZ-1/*.* \
		$(1)/lib/firmware/ath11k/IPQ5018/hw1.0/
	$(INSTALL_DIR) $(1)/lib/firmware/ath11k/QCN6122/hw1.0
	$(INSTALL_DATA) \
		$(BUILD_DIR)/$(ATH11K_LEGACY_FW_SUBDIR)/ath11k-firmware/IPQ5018_QCN6122_QCN6122/hw1.0/2.7.0.1/WLAN.HK.2.7.0.1-01744-QCAHKSWPL_SILICONZ-1/qcn6122/*.* \
		$(1)/lib/firmware/ath11k/QCN6122/hw1.0/
endef

define Package/ath11k-firmware-ipq6018/install
	$(INSTALL_DIR) $(1)/lib/firmware/IPQ6018
	$(INSTALL_DATA) \
		$(PKG_BUILD_DIR)/IPQ6018/hw1.0/testing/2.12/WLAN.HK.2.12-01460-QCAHKSWPL_SILICONZ-1/* \
		$(1)/lib/firmware/IPQ6018/
endef

define Package/ath11k-firmware-ipq8074/install
	$(INSTALL_DIR) $(1)/lib/firmware/IPQ8074
	$(INSTALL_DATA) \
		$(PKG_BUILD_DIR)/IPQ8074/hw2.0/testing/2.12/WLAN.HK.2.12-01460-QCAHKSWPL_SILICONZ-1/* \
		$(1)/lib/firmware/IPQ8074/
endef

define Package/ath11k-firmware-qcn9074/install
	$(INSTALL_DIR) $(1)/lib/firmware/ath11k/QCN9074/hw1.0
	$(INSTALL_DATA) \
		$(PKG_BUILD_DIR)/QCN9074/hw1.0/testing/2.12/WLAN.HK.2.12-01460-QCAHKSWPL_SILICONZ-1/* \
		$(1)/lib/firmware/ath11k/QCN9074/hw1.0/
endef

$(eval $(call BuildPackage,ath11k-firmware-ipq5018))
$(eval $(call BuildPackage,ath11k-firmware-ipq5018-qcn6122))
$(eval $(call BuildPackage,ath11k-firmware-ipq6018))
$(eval $(call BuildPackage,ath11k-firmware-ipq8074))
$(eval $(call BuildPackage,ath11k-firmware-qcn9074))
