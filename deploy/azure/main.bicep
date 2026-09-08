targetScope = 'resourceGroup'

// Deploy to the selected student subscription with the Azure CLI's --subscription
// argument. This template creates no role assignments or deployment credentials.

@description('Azure region containing the confirmed ARM64 VM capacity.')
@allowed([
  'swedencentral'
])
param location string = 'swedencentral'

@description('Short lowercase resource name prefix.')
@minLength(3)
@maxLength(24)
param namePrefix string = 'cyberwatch-yamk'

@description('Region-unique public DNS label for the static IPv4 address.')
@minLength(3)
@maxLength(63)
param dnsLabel string = 'cyberwatch-yamk-afe8ae-20260908'

@description('Key-only Linux administrator. Deployment scripts use the default cywadmin.')
param adminUsername string = 'cywadmin'

@description('SSH public key for cywadmin. Inbound SSH is blocked; use Azure Run Command for administration.')
@minLength(40)
param adminSshPublicKey string

@description('Exact stable Canonical Ubuntu 24.04 ARM64 image version. Supply the verified version, never latest or a daily image.')
@minLength(5)
param ubuntuImageVersion string = '24.04.202608270'

@description('Cloud-init YAML supplied by the deployment operator. Encoded as VM custom data inside this template.')
@secure()
param cloudInit string

var vmName = namePrefix
var artifactContainerName = 'artifacts'
var resourceTags = union(resourceGroup().tags, {
  project: 'Cyberwatch'
  course: 'YAMK282-YAMK283'
  environment: 'student'
})

resource networkSecurityGroup 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: '${namePrefix}-nsg'
  location: location
  tags: resourceTags
  properties: {
    securityRules: [
      {
        name: 'Allow-Public-HTTP-HTTPS'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRanges: [
            '80'
            '443'
          ]
        }
      }
      // Override Azure's default VNet/LB inbound allows as well: no SSH or direct
      // application-port ingress. Established outbound responses are stateful.
      {
        name: 'Deny-All-Other-Inbound'
        properties: {
          priority: 200
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

resource virtualNetwork 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${namePrefix}-vnet'
  location: location
  tags: resourceTags
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.42.0.0/24'
      ]
    }
    subnets: [
      {
        name: 'application'
        properties: {
          addressPrefix: '10.42.0.0/27'
          defaultOutboundAccess: false
          networkSecurityGroup: {
            id: networkSecurityGroup.id
          }
        }
      }
    ]
  }
}

resource publicIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: '${namePrefix}-ip'
  location: location
  tags: resourceTags
  sku: {
    name: 'Standard'
    tier: 'Regional'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
    idleTimeoutInMinutes: 4
    dnsSettings: {
      domainNameLabel: dnsLabel
    }
  }
}

resource networkInterface 'Microsoft.Network/networkInterfaces@2024-05-01' = {
  name: '${namePrefix}-nic'
  location: location
  tags: resourceTags
  properties: {
    enableAcceleratedNetworking: false
    enableIPForwarding: false
    ipConfigurations: [
      {
        name: 'primary'
        properties: {
          primary: true
          privateIPAllocationMethod: 'Dynamic'
          privateIPAddressVersion: 'IPv4'
          subnet: {
            id: '${virtualNetwork.id}/subnets/application'
          }
          publicIPAddress: {
            id: publicIp.id
          }
        }
      }
    ]
  }
}

// Detaching this disk on VM deletion preserves the database. Deleting the entire
// resource group still deletes its disk, so recovery also needs a separate backup.
resource dataDisk 'Microsoft.Compute/disks@2024-03-02' = {
  name: '${namePrefix}-data'
  location: location
  tags: resourceTags
  sku: {
    name: 'StandardSSD_LRS'
  }
  properties: {
    diskSizeGB: 4
    creationData: {
      createOption: 'Empty'
    }
    encryption: {
      type: 'EncryptionAtRestWithPlatformKey'
    }
    networkAccessPolicy: 'DenyAll'
    publicNetworkAccess: 'Disabled'
  }
}

resource virtualMachine 'Microsoft.Compute/virtualMachines@2024-03-01' = {
  name: vmName
  location: location
  tags: resourceTags
  properties: {
    hardwareProfile: {
      vmSize: 'Standard_B2pts_v2'
    }
    osProfile: {
      computerName: vmName
      adminUsername: adminUsername
      customData: base64(cloudInit)
      linuxConfiguration: {
        disablePasswordAuthentication: true
        provisionVMAgent: true
        ssh: {
          publicKeys: [
            {
              path: '/home/${adminUsername}/.ssh/authorized_keys'
              keyData: adminSshPublicKey
            }
          ]
        }
      }
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: 'ubuntu-24_04-lts'
        sku: 'server-arm64'
        version: ubuntuImageVersion
      }
      osDisk: {
        name: '${namePrefix}-os'
        createOption: 'FromImage'
        deleteOption: 'Delete'
        diskSizeGB: 32
        caching: 'ReadWrite'
        managedDisk: {
          storageAccountType: 'StandardSSD_LRS'
        }
      }
      dataDisks: [
        {
          name: dataDisk.name
          lun: 0
          createOption: 'Attach'
          deleteOption: 'Detach'
          caching: 'None'
          managedDisk: {
            id: dataDisk.id
          }
        }
      ]
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: networkInterface.id
          properties: {
            primary: true
            deleteOption: 'Delete'
          }
        }
      ]
    }
    diagnosticsProfile: {
      bootDiagnostics: {
        enabled: false
      }
    }
  }
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'cyw${uniqueString(resourceGroup().id)}'
  location: location
  tags: resourceTags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowCrossTenantReplication: false
    // Authenticated public access is needed for the operator's upload and the
    // VM's short-lived read-only SAS download; no anonymous blob access exists.
    publicNetworkAccess: 'Enabled'
    allowSharedKeyAccess: true
    encryption: {
      keySource: 'Microsoft.Storage'
      services: {
        blob: {
          enabled: true
          keyType: 'Account'
        }
      }
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
  properties: {}
}

resource artifactContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: artifactContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource artifactLifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'Delete-Expired-Deployment-Artifacts'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: {
              blobTypes: [
                'blockBlob'
              ]
              // Container-qualified prefix deliberately excludes any future
              // backup container; its retention must be designed separately.
              prefixMatch: [
                '${artifactContainerName}/'
              ]
            }
            actions: {
              baseBlob: {
                delete: {
                  daysAfterModificationGreaterThan: 7
                }
              }
            }
          }
        }
      ]
    }
  }
}

output vmName string = virtualMachine.name
output ip string = publicIp.properties.ipAddress
output fqdn string = publicIp.properties.dnsSettings.fqdn
output storageAccount string = storageAccount.name
output container string = artifactContainer.name
output dataDiskId string = dataDisk.id
