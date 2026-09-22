targetScope = 'resourceGroup'

// Steady-state only: every resource must already exist. ado_infra.py enforces
// this before plan and apply. No VM PUT, bootstrap, identity or RBAC operations.
@allowed(['swedencentral'])
param location string = 'swedencentral'

@minLength(3)
@maxLength(24)
param namePrefix string

@minLength(3)
@maxLength(63)
param dnsLabel string

@minLength(3)
@maxLength(24)
param storageAccountName string

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
    privateEndpointVNetPolicies: 'Disabled'
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
    ddosSettings: {
      protectionMode: 'VirtualNetworkInherited'
    }
  }
}

// The existing NIC is bootstrap-owned together with the VM. Its existence is
// checked by ado_infra.py; no PUT can reset provider-specific NIC properties.

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

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
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
  properties: {
    // Preserve the confirmed current policy; enabling retention is a separate
    // reviewed data-retention change, not an implicit default reset.
    deleteRetentionPolicy: {
      enabled: false
      allowPermanentDelete: false
    }
  }
}

resource artifactContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: artifactContainerName
  properties: {
    publicAccess: 'None'
    defaultEncryptionScope: '$account-encryption-key'
    denyEncryptionScopeOverride: false
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
