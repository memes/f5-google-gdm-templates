# Copyright 2019 F5 Networks All rights reserved.
#
# Version 3.6.0

"""Creates BIG-IP"""
COMPUTE_URL_BASE = 'https://www.googleapis.com/compute/v1/'


def FirewallRuleMgmt(context):
    # Build Management firewall rule
    source_list = str(context.properties['restrictedSrcAddress']).split()
    firewallRuleMgmt = {
        'name': 'mgmtfw-' + context.env['deployment'],
        'type': 'compute.v1.firewall',
        'properties': {
            'network': ''.join([COMPUTE_URL_BASE, 'projects/',
                                context.env['project'], '/global/networks/',
                                context.properties['mgmtNetwork']]),
            'sourceRanges': source_list,
            'targetTags': ['mgmtfw-' + context.env['deployment']],
            'allowed': [{
                "IPProtocol": "TCP",
                "ports": [str(context.properties['mgmtGuiPort']), '22'],
                },
            ]
        }
    }
    return firewallRuleMgmt


def Metadata(context,group, storageName, licenseType):

  # SETUP VARIABLES
  ## Template Analytics
  ALLOWUSAGEANALYTICS = str(context.properties['allowUsageAnalytics']).lower()
  if ALLOWUSAGEANALYTICS in ['yes', 'true']:
      CUSTHASH = 'CUSTOMERID=`curl -s "http://metadata.google.internal/computeMetadata/v1/project/numeric-project-id" -H "Metadata-Flavor: Google" |sha512sum|cut -d " " -f 1`;\nDEPLOYMENTID=`curl -s "http://metadata.google.internal/computeMetadata/v1/instance/id" -H "Metadata-Flavor: Google"|sha512sum|cut -d " " -f 1`;'
      SENDANALYTICS = ' --metrics "cloudName:google,region:' + context.properties['region'] + ',bigipVersion:' + context.properties['imageName'] + ',customerId:${CUSTOMERID},deploymentId:${DEPLOYMENTID},templateName:f5-existing-stack-same-net-cluster-payg-2nic-bigip.py,templateVersion:3.6.0,licenseType:payg"'
  else:
      CUSTHASH = '# No template analytics'
      SENDANALYTICS = ''

  ## Phone home
  ALLOWPHONEHOME = str(context.properties['allowPhoneHome']).lower()
  if ALLOWPHONEHOME in ['yes', 'true']:
      PHONEHOME = '"tmsh modify sys software update auto-phonehome enabled"'
  else:
      PHONEHOME = '"tmsh modify sys software update auto-phonehome disabled"'

  ## ntp servers
  ntp_servers = str(context.properties['ntpServer']).split()
  ntp_list = ''
  for ntp_server in ntp_servers:
      ntp_list = ntp_list + ' --ntp ' + ntp_server
  timezone = ' --tz UTC'
  if context.properties['timezone']:
      timezone = " --tz {0}".format(str(context.properties['timezone']))


  ## Onboard
  if group == "create" and licenseType == "byol":
      LICENSE = ' --license ' + context.properties['licenseKey1']
  elif group == "join" and licenseType == "byol":
      LICENSE = ' --license ' + context.properties['licenseKey2']
  else:
      LICENSE = ''

  # Provisioning modules
  PROVISIONING_MODULES = ','.join(context.properties['bigIpModules'].split('-'))

  ## Cluster
  if group == "create":
      CLUSTERJS = ' '.join(["nohup /config/waitThenRun.sh",
                        "f5-rest-node /config/cloud/gce/node_modules/@f5devcentral/f5-cloud-libs/scripts/cluster.js",
                        "-o /var/log/cloud/google/cluster.log",
                        "--log-level " + str(context.properties['logLevel']),
                        "--host localhost",
                        "--wait-for CUSTOM_CONFIG_DONE",
                        "--signal CLUSTER_DONE",
                        "--user admin",
                        "--password-url file:///config/cloud/gce/.adminPassword",
                        "--password-encrypted",
                        "--cloud gce",
                        "--provider-options 'region:" + context.properties['region'] + ",storageBucket:" + storageName  + "'",
                        "--master",
                        "--config-sync-ip ${INT1ADDRESS}",
                        "--create-group",
                        "--device-group failover_group",
                        "--sync-type sync-failover",
                        "--network-failover",
                        "--device ${HOSTNAME}",
                        "--auto-sync",
                        "--no-reboot",
                        "2>&1 >> /var/log/cloud/google/install.log < /dev/null &"
      ])
      CFEJSON = '\n'.join([
                        'bigip1_host=$(curl -s -f --retry 20 \'http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/ip\' -H \'Metadata-Flavor: Google\')',
                        'cat <<EOF > /config/cloud/cfe_config.json',
                        '{',
                        '    "class": "Cloud_Failover",',
                        '    "environment": "gcp",',
                        '    "externalStorage": {',
                        '        "scopingTags": {',
                        '            "f5_cloud_failover_label": "' + context.env['deployment'] + '"',
                        '        }',
                        '    },',
                        '    "failoverAddresses": {',
                        '        "scopingTags": {',
                        '            "f5_cloud_failover_label": "' + context.env['deployment'] + '"',
                        '        }',
                        '    },',
                        '    "failoverRoutes": {',
                        '        "scopingTags": {',
                        '            "f5_cloud_failover_label": "' + context.env['deployment'] + '"',
                        '        },',
                        '        "scopingAddressRanges": [',
                        '            {',
                        '                "range": "192.0.2.0/24"',
                        '            }',
                        '        ],',
                        '        "defaultNextHopAddresses": {',
                        '            "discoveryType": "static",',
                        '            "items": [',
                        '            "${bigip1_host}"',
                        '            ]',
                        '        }',
                        '    },',
                        '    "controls": {',
                        '        "class": "Controls",',
                        '        "logLevel": "' + str(context.properties['logLevel']) + '"',
                        '    }',
                        '}',
                        'EOF'
      ])
      CREATEVA = ''
      POSTCFE = '\n'.join([
                        'cfe_file_loc="/config/cloud/cfe_config.json"',
                        'wait_for_ready cloud-failover',
                        'cfe_response_code=$(/usr/bin/curl -skvvu admin:$passwd -w "%{http_code}" -X POST -H "Content-Type: application/json" https://localhost:${mgmtGuiPort}/mgmt/shared/cloud-failover/declare -d @$cfe_file_loc -o /dev/null)',
                        'if [[ $cfe_response_code == 200 || $cfe_response_code == 502 ]]; then',
                        '    echo "Deployment of CFE application to localhost succeeded."',
                        '    cfe_deployed="yes"',
                        'else',
                        '    echo "Failed to deploy CFE application; continuing..."',
                        'fi'
      ])
      POSTCFEVA = ''
      RUNCREATEVA = '\n'.join(['nohup /config/waitThenRun.sh f5-rest-node /config/cloud/gce/node_modules/@f5devcentral/f5-cloud-libs/scripts/runScript.js --file /config/cloud/gce/rm-password.sh --cwd /config/cloud/gce -o /var/log/cloud/google/rm-password.log --wait-for CLUSTER_DONE --signal RM_PASSWORD_DONE --log-level ' + str(context.properties['logLevel']) + ' 2>&1 >> /var/log/cloud/google/install.log < /dev/null &'])
      SYNC = ''
  elif group == "join":
      CLUSTERJS = ' '.join(["nohup /config/waitThenRun.sh",
                        "f5-rest-node /config/cloud/gce/node_modules/@f5devcentral/f5-cloud-libs/scripts/cluster.js",
                        "-o /var/log/cloud/google/cluster.log",
                        "--log-level " + str(context.properties['logLevel']),
                        "--host localhost",
                        "--wait-for CUSTOM_CONFIG_DONE",
                        "--signal CLUSTER_DONE",
                        "--user admin",
                        "--password-url file:///config/cloud/gce/.adminPassword",
                        "--password-encrypted",
                        "--cloud gce",
                        "--provider-options 'region:" + context.properties['region'] + ",storageBucket:" + storageName  + "'",
                        "--config-sync-ip ${INT1ADDRESS}",
                        "--join-group",
                        "--device-group failover_group",
                        "--remote-host ",
                        "$(ref.bigip1-" + context.env['deployment'] + ".networkInterfaces[1].networkIP)",
                        "--no-reboot",
                        "2>&1 >> /var/log/cloud/google/install.log < /dev/null &"
             ])
      CFEJSON = '\n'.join([
                        'bigip2_host=$(curl -s -f --retry 20 \'http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/ip\' -H \'Metadata-Flavor: Google\')',
                        'cat <<EOF > /config/cloud/cfe_config.json',
                        '{',
                        '    "class": "Cloud_Failover",',
                        '    "environment": "gcp",',
                        '    "externalStorage": {',
                        '        "scopingTags": {',
                        '            "f5_cloud_failover_label": "' + context.env['deployment'] + '"',
                        '        }',
                        '    },',
                        '    "failoverAddresses": {',
                        '        "scopingTags": {',
                        '            "f5_cloud_failover_label": "' + context.env['deployment'] + '"',
                        '        }',
                        '    },',
                        '    "failoverRoutes": {',
                        '        "scopingTags": {',
                        '            "f5_cloud_failover_label": "' + context.env['deployment'] + '"',
                        '        },',
                        '        "scopingAddressRanges": [',
                        '            {',
                        '                "range": "192.0.2.0/24"',
                        '            }',
                        '        ],',
                        '        "defaultNextHopAddresses": {',
                        '            "discoveryType": "static",',
                        '            "items": [',
                        '            "$(ref.bigip1-' + context.env['deployment'] + '.networkInterfaces[0].networkIP)",',
                        '            "${bigip2_host}"',
                        '            ]',
                        '        }',
                        '    },',
                        '    "controls": {',
                        '        "class": "Controls",',
                        '        "logLevel": "' + str(context.properties['logLevel']) + '"',
                        '    }',
                        '}',
                        'EOF'
      ])
      CREATEVA = '\n'.join([
                        'cat <<\'EOF\' > /config/cloud/gce/create-va.sh',
                        '#!/bin/bash',
                        'date',
                        'echo "starting create-va.sh"',
                        'baseUrl="http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0"',
                        'forwardedIps=$(curl -s -f --retry 20 -H "Metadata-Flavor: Google" "${baseUrl}/forwarded-ips/?recursive=true")',
                        'aliasIps=$(curl -s -f --retry 20 -H "Metadata-Flavor: Google" "${baseUrl}/ip-aliases/?recursive=true")',
                        'ipsList=()',
                        'for i in $(echo $forwardedIps | jq -c -r \'.[]\') ; do',
                        '   ipsList=("${ipsList[@]}" "$i")',
                        'done',
                        'for i in $(echo $aliasIps | jq -c -r \'.[]\') ; do',
                        '   i=$(echo $i | cut -d "/" -f1)',
                        '   ipsList=("${ipsList[@]}" "$i")',
                        'done',
                        'for addr in "${ipsList[@]}"; do',
                        '   echo "creating virtual address: $addr"',
                        '   /usr/bin/tmsh create ltm virtual-address $addr address $addr',
                        'done',
                        'function wait_for_ready {',
                        '   app=$1',
                        '   checks=0',
                        '   ready_response=""',
                        '   ready_response_declare=""',
                        '   checks_max=120',
                        '   while [ $checks -lt $checks_max ] ; do',
                        '      ready_response=$(curl -sku admin:$passwd -w "%{http_code}" -X GET  https://localhost:${mgmtGuiPort}/mgmt/shared/${app}/info -o /dev/null)',
                        '      ready_response_declare=$(curl -sku admin:$passwd -w "%{http_code}" -X GET  https://localhost:${mgmtGuiPort}/mgmt/shared/${app}/declare -o /dev/null)',
                        '      if [[ $ready_response == *200 ]] && [[ $ready_response_declare == *204  || $ready_response_declare == *200 ]]; then',
                        '          echo "${app} is ready"',
                        '          break',
                        '      else',
                        '         echo "${app}" is not ready: $checks, response: $ready_response $ready_response_declare',
                        '         let checks=checks+1',
                        '         if [[ $checks == $((checks_max/2)) ]]; then',
                        '             echo "restarting restnoded"'
                        '             bigstart restart restnoded',
                        '         fi',
                        '         sleep 15',
                        '      fi',
                        '   done',
                        '   if [[ $ready_response != *200 ]] && [[ $ready_response_declare != *204 || $ready_response_declare != *200 ]]; then',
                        '      error_exit "$LINENO: ${app} was not installed correctly. Exit."',
                        '   fi',
                        '}',
                        'cfe_file_loc="/config/cloud/cfe_config.json"',
                        'wait_for_ready cloud-failover',
                        'cfe_response_code=$(/usr/bin/curl -skvvu admin:$passwd -w "%{http_code}" -X POST -H "Content-Type: application/json" -H "Expect:" https://localhost:${mgmtGuiPort}/mgmt/shared/cloud-failover/declare -d @$cfe_file_loc -o /dev/null)',
                        'if [[ $cfe_response_code == 200 || $cfe_response_code == 502 ]]; then',
                        '    echo "Deployment of CFE application to localhost succeeded."',
                        '    cfe_deployed="yes"',
                        'else',
                        '    echo "Failed to deploy CFE application; continuing..."',
                        'fi',
                        '/usr/bin/tmsh save sys config',
                        '# run failover to ensure objects are on the correct BIG-IP',
                        '/config/failover/tgactive',
                        'date',
                        'EOF'
      ])
      POSTCFE = ''
      RUNCREATEVA = '\n'.join([
                           'nohup /config/waitThenRun.sh f5-rest-node /config/cloud/gce/node_modules/@f5devcentral/f5-cloud-libs/scripts/runScript.js --file /config/cloud/gce/create-va.sh --cwd /config/cloud/gce --output /var/log/cloud/google/create-va.log --wait-for CLUSTER_DONE --signal CREATE_VA_DONE --log-level ' + str(context.properties['logLevel']) + ' 2>&1 >> /var/log/cloud/google/install.log < /dev/null & ',
                           'nohup /config/waitThenRun.sh f5-rest-node /config/cloud/gce/node_modules/@f5devcentral/f5-cloud-libs/scripts/runScript.js --file /config/cloud/gce/rm-password.sh --cwd /config/cloud/gce -o /var/log/cloud/google/rm-password.log --wait-for CREATE_VA_DONE --signal RM_PASSWORD_DONE --log-level ' + str(context.properties['logLevel']) + ' 2>&1 >> /var/log/cloud/google/install.log < /dev/null &'
      ])
      SYNC = 'tmsh modify cm device-group failover_group devices modify { $HOSTNAME { set-sync-leader } }'
  else:
      CLUSTERJS = ''
      SYNC = ''
      CFEJSON = ''
      CREATEVA = ''
      RUNCREATEVA = ''
      POSTCFE = ''

  ## generate metadata
  metadata = {
              'items': [{
                  'key': 'startup-script',
                  'value': ('\n'.join(['#!/bin/bash',
                                    'if [ -f /config/startupFinished ]; then',
                                    '    exit',
                                    'fi',
                                    'if [ ! -f /config/cloud/gce/FIRST_BOOT_COMPLETE ]; then',
                                    'mkdir -p /config/cloud/gce',
                                    'cat <<\'EOF\' > /config/installCloudLibs.sh',
                                    '#!/bin/bash',
                                    'echo about to execute',
                                    'checks=0',
                                    'while [ $checks -lt 120 ]; do echo checking mcpd',
                                    '    tmsh -a show sys mcp-state field-fmt | grep -q running',
                                    '    if [ $? == 0 ]; then',
                                    '        echo mcpd ready',
                                    '        break',
                                    '    fi',
                                    '    echo mcpd not ready yet',
                                    '    let checks=checks+1',
                                    '    sleep 10',
                                    'done',
                                    'echo loading verifyHash script',
                                    'if ! tmsh load sys config merge file /config/verifyHash; then',
                                    '    echo cannot validate signature of /config/verifyHash',
                                    '    exit',
                                    'fi',
                                    'echo loaded verifyHash',
                                    'declare -a filesToVerify=(\"/config/cloud/f5-cloud-libs.tar.gz\" \"/config/cloud/f5-cloud-libs-gce.tar.gz\" \"/config/cloud/f5-appsvcs-3.18.0-4.noarch.rpm\" \"/config/cloud/f5-cloud-failover-1.3.0-0.noarch.rpm\" \"/config/cloud/f5.service_discovery.tmpl\")',
                                    'for fileToVerify in \"${filesToVerify[@]}\"',
                                    'do',
                                    '    echo verifying \"$fileToVerify\"',
                                    '    if ! tmsh run cli script verifyHash \"$fileToVerify\"; then',
                                    '        echo \"$fileToVerify\" is not valid',
                                    '        exit 1',
                                    '    fi',
                                    '    echo verified \"$fileToVerify\"',
                                    'done',
                                    'mkdir -p /config/cloud/gce/node_modules/@f5devcentral',
                                    'echo expanding f5-cloud-libs.tar.gz',
                                    'tar xvfz /config/cloud/f5-cloud-libs.tar.gz -C /config/cloud/gce/node_modules/@f5devcentral',
                                    'echo expanding f5-cloud-libs-gce.tar.gz',
                                    'tar xvfz /config/cloud/f5-cloud-libs-gce.tar.gz -C /config/cloud/gce/node_modules/@f5devcentral',
                                    'touch /config/cloud/cloudLibsReady',
                                    'EOF',
                                    'echo \'Y2xpIHNjcmlwdCAvQ29tbW9uL3ZlcmlmeUhhc2ggewpwcm9jIHNjcmlwdDo6cnVuIHt9IHsKICAgICAgICBpZiB7W2NhdGNoIHsKICAgICAgICAgICAgc2V0IGhhc2hlcyhmNS1jbG91ZC1saWJzLnRhci5neikgYTgwYWY0MzhhNDk5NDE4YmNmYzI4Mjc4NGI4Nzg3ZjA3M2JkZWI5OWQ4YzI2YzZiYzE2NmNkMDRmMGMzMTkwYTgyM2JiN2UzZGNmMzMwNWQ4ZDRlOWJlM2UxNjEyMWFmNTk5MTdkYTJiYTE1ZDRkYzM5OTQ4YzRhNTc4MDljMDQKICAgICAgICAgICAgc2V0IGhhc2hlcyhmNS1jbG91ZC1saWJzLWF3cy50YXIuZ3opIDZmMmViMDc4MmRhNjhmYTE4ODJkNDhhMzQ5ZjUzMDUxMTM4MTk3ZGEzOWU0NTkxZDdjZTFkZjEzNGUzMWQwZTQyNjc4OTRmOWFhNjliODBlZGFkMzU2NDliMmZhZGM4YWVkNTAxODg5YzcxZTVmZmE0ZmU0MzcxNWM2MzQwMmEyCiAgICAgICAgICAgIHNldCBoYXNoZXMoZjUtY2xvdWQtbGlicy1henVyZS50YXIuZ3opIDZkYjI4NzhhMmMxMGQ5ODU1MGVkZWQ2YjY2ZjA0NzQ1MTZjMTk1MmQzNjA1MjE3MTY0ZTNiNTI2MWM3NzE0MTkyMDFkOTRjN2NkYjA3NzQ0YzlkNWRiODk0MzM0ZjkzMzgwOTYzMjE3YjY3MGQ4N2QzMTUxYmZjZGIzMDFjMjk1CiAgICAgICAgICAgIHNldCBoYXNoZXMoZjUtY2xvdWQtbGlicy1nY2UudGFyLmd6KSBhNWNmYWVkMWZlMzNkYTY3N2IzZjEwZGMxYTdjYTgyZjU3MzlmZjI0ZTQ1ZTkxYjNhOGY3YjA2ZDZiMmUyODBlNWYxZWFmNWZlMmQzMzAwOWIyY2M2N2MxMGYyZDkwNmFhYjI2Zjk0MmQ1OTFiNjhmYThhN2ZkZGZkNTRhMGVmZQogICAgICAgICAgICBzZXQgaGFzaGVzKGY1LWNsb3VkLWxpYnMtb3BlbnN0YWNrLnRhci5neikgNWM4M2ZlNmE5M2E2ZmNlYjVhMmU4NDM3YjVlZDhjYzlmYWY0YzE2MjFiZmM5ZTZhMDc3OWY2YzIxMzdiNDVlYWI4YWUwZTdlZDc0NWM4Y2Y4MjFiOTM3MTI0NWNhMjk3NDljYTBiN2U1NjYzOTQ5ZDc3NDk2Yjg3MjhmNGIwZjkKICAgICAgICAgICAgc2V0IGhhc2hlcyhmNS1jbG91ZC1saWJzLWNvbnN1bC50YXIuZ3opIGEzMmFhYjM5NzA3M2RmOTJjYmJiYTUwNjdlNTgyM2U5YjVmYWZjYTg2MmEyNThiNjBiNmI0MGFhMDk3NWMzOTg5ZDFlMTEwZjcwNjE3N2IyZmZiZTRkZGU2NTMwNWEyNjBhNTg1NjU5NGNlN2FkNGVmMGM0N2I2OTRhZTRhNTEzCiAgICAgICAgICAgIHNldCBoYXNoZXMoYXNtLXBvbGljeS1saW51eC50YXIuZ3opIDYzYjVjMmE1MWNhMDljNDNiZDg5YWYzNzczYmJhYjg3YzcxYTZlN2Y2YWQ5NDEwYjIyOWI0ZTBhMWM0ODNkNDZmMWE5ZmZmMzlkOTk0NDA0MWIwMmVlOTI2MDcyNDAyNzQxNGRlNTkyZTk5ZjRjMjQ3NTQxNTMyM2UxOGE3MmUwCiAgICAgICAgICAgIHNldCBoYXNoZXMoZjUuaHR0cC52MS4yLjByYzQudG1wbCkgNDdjMTlhODNlYmZjN2JkMWU5ZTljMzVmMzQyNDk0NWVmODY5NGFhNDM3ZWVkZDE3YjZhMzg3Nzg4ZDRkYjEzOTZmZWZlNDQ1MTk5YjQ5NzA2NGQ3Njk2N2IwZDUwMjM4MTU0MTkwY2EwYmQ3Mzk0MTI5OGZjMjU3ZGY0ZGMwMzQKICAgICAgICAgICAgc2V0IGhhc2hlcyhmNS5odHRwLnYxLjIuMHJjNi50bXBsKSA4MTFiMTRiZmZhYWI1ZWQwMzY1ZjAxMDZiYjVjZTVlNGVjMjIzODU2NTVlYTNhYzA0ZGUyYTM5YmQ5OTQ0ZjUxZTM3MTQ2MTlkYWU3Y2E0MzY2MmM5NTZiNTIxMjIyODg1OGYwNTkyNjcyYTI1NzlkNGE4Nzc2OTE4NmUyY2JmZQogICAgICAgICAgICBzZXQgaGFzaGVzKGY1Lmh0dHAudjEuMi4wcmM3LnRtcGwpIDIxZjQxMzM0MmU5YTdhMjgxYTBmMGUxMzAxZTc0NWFhODZhZjIxYTY5N2QyZTZmZGMyMWRkMjc5NzM0OTM2NjMxZTkyZjM0YmYxYzJkMjUwNGMyMDFmNTZjY2Q3NWM1YzEzYmFhMmZlNzY1MzIxMzY4OWVjM2M5ZTI3ZGZmNzdkCiAgICAgICAgICAgIHNldCBoYXNoZXMoZjUuYXdzX2FkdmFuY2VkX2hhLnYxLjMuMHJjMS50bXBsKSA5ZTU1MTQ5YzAxMGMxZDM5NWFiZGFlM2MzZDJjYjgzZWMxM2QzMWVkMzk0MjQ2OTVlODg2ODBjZjNlZDVhMDEzZDYyNmIzMjY3MTFkM2Q0MGVmMmRmNDZiNzJkNDE0YjRjYjhlNGY0NDVlYTA3MzhkY2JkMjVjNGM4NDNhYzM5ZAogICAgICAgICAgICBzZXQgaGFzaGVzKGY1LmF3c19hZHZhbmNlZF9oYS52MS40LjByYzEudG1wbCkgZGUwNjg0NTUyNTc0MTJhOTQ5ZjFlYWRjY2FlZTg1MDYzNDdlMDRmZDY5YmZiNjQ1MDAxYjc2ZjIwMDEyNzY2OGU0YTA2YmUyYmJiOTRlMTBmZWZjMjE1Y2ZjMzY2NWIwNzk0NWU2ZDczM2NiZTFhNGZhMWI4OGU4ODE1OTAzOTYKICAgICAgICAgICAgc2V0IGhhc2hlcyhmNS5hd3NfYWR2YW5jZWRfaGEudjEuNC4wcmMyLnRtcGwpIDZhYjBiZmZjNDI2ZGY3ZDMxOTEzZjlhNDc0YjFhMDc4NjA0MzVlMzY2YjA3ZDc3YjMyMDY0YWNmYjI5NTJjMWYyMDdiZWFlZDc3MDEzYTE1ZTQ0ZDgwZDc0ZjMyNTNlN2NmOWZiYmUxMmE5MGVjNzEyOGRlNmZhY2QwOTdkNjhmCiAgICAgICAgICAgIHNldCBoYXNoZXMoZjUuYXdzX2FkdmFuY2VkX2hhLnYxLjQuMHJjMy50bXBsKSAyZjIzMzliNGJjM2EyM2M5Y2ZkNDJhYWUyYTZkZTM5YmEwNjU4MzY2ZjI1OTg1ZGUyZWE1MzQxMGE3NDVmMGYxOGVlZGM0OTFiMjBmNGE4ZGJhOGRiNDg5NzAwOTZlMmVmZGNhN2I4ZWZmZmExYTgzYTc4ZTVhYWRmMjE4YjEzNAogICAgICAgICAgICBzZXQgaGFzaGVzKGY1LmF3c19hZHZhbmNlZF9oYS52MS40LjByYzQudG1wbCkgMjQxOGFjOGIxZjE4ODRjNWMwOTZjYmFjNmE5NGQ0MDU5YWFhZjA1OTI3YTZhNDUwOGZkMWYyNWI4Y2M2MDc3NDk4ODM5ZmJkZGE4MTc2ZDJjZjJkMjc0YTI3ZTZhMWRhZTJhMWUzYTBhOTk5MWJjNjVmYzc0ZmMwZDAyY2U5NjMKICAgICAgICAgICAgc2V0IGhhc2hlcyhmNS5hd3NfYWR2YW5jZWRfaGEudjEuNC4wcmM1LnRtcGwpIDVlNTgyMTg3YWUxYTYzMjNlMDk1ZDQxZWRkZDQxMTUxZDZiZDM4ZWI4M2M2MzQ0MTBkNDUyN2EzZDBlMjQ2YThmYzYyNjg1YWIwODQ5ZGUyYWRlNjJiMDI3NWY1MTI2NGQyZGVhY2NiYzE2Yjc3MzQxN2Y4NDdhNGExZWE5YmM0CiAgICAgICAgICAgIHNldCBoYXNoZXMoYXNtLXBvbGljeS50YXIuZ3opIDJkMzllYzYwZDAwNmQwNWQ4YTE1NjdhMWQ4YWFlNzIyNDE5ZThiMDYyYWQ3N2Q2ZDlhMzE2NTI5NzFlNWU2N2JjNDA0M2Q4MTY3MWJhMmE4YjEyZGQyMjllYTQ2ZDIwNTE0NGY3NTM3NGVkNGNhZTU4Y2VmYThmOWFiNjUzM2U2CiAgICAgICAgICAgIHNldCBoYXNoZXMoZGVwbG95X3dhZi5zaCkgMWEzYTNjNjI3NGFiMDhhN2RjMmNiNzNhZWRjOGQyYjJhMjNjZDllMGViMDZhMmUxNTM0YjM2MzJmMjUwZjFkODk3MDU2ZjIxOWQ1YjM1ZDNlZWQxMjA3MDI2ZTg5OTg5Zjc1NDg0MGZkOTI5NjljNTE1YWU0ZDgyOTIxNGZiNzQKICAgICAgICAgICAgc2V0IGhhc2hlcyhmNS5wb2xpY3lfY3JlYXRvci50bXBsKSAwNjUzOWUwOGQxMTVlZmFmZTU1YWE1MDdlY2I0ZTQ0M2U4M2JkYjFmNTgyNWE5NTE0OTU0ZWY2Y2E1NmQyNDBlZDAwYzdiNWQ2N2JkOGY2N2I4MTVlZTlkZDQ2NDUxOTg0NzAxZDA1OGM4OWRhZTI0MzRjODk3MTVkMzc1YTYyMAogICAgICAgICAgICBzZXQgaGFzaGVzKGY1LnNlcnZpY2VfZGlzY292ZXJ5LnRtcGwpIDQ4MTFhOTUzNzJkMWRiZGJiNGY2MmY4YmNjNDhkNGJjOTE5ZmE0OTJjZGEwMTJjODFlM2EyZmU2M2Q3OTY2Y2MzNmJhODY3N2VkMDQ5YTgxNGE5MzA0NzMyMzRmMzAwZDNmOGJjZWQyYjBkYjYzMTc2ZDUyYWM5OTY0MGNlODFiCiAgICAgICAgICAgIHNldCBoYXNoZXMoZjUuY2xvdWRfbG9nZ2VyLnYxLjAuMC50bXBsKSA2NGEwZWQzYjVlMzJhMDM3YmE0ZTcxZDQ2MDM4NWZlOGI1ZTFhZWNjMjdkYzBlODUxNGI1MTE4NjM5NTJlNDE5YTg5ZjRhMmE0MzMyNmFiYjU0M2JiYTliYzM0Mzc2YWZhMTE0Y2VkYTk1MGQyYzNiZDA4ZGFiNzM1ZmY1YWQyMAogICAgICAgICAgICBzZXQgaGFzaGVzKGY1LWFwcHN2Y3MtMy41LjEtNS5ub2FyY2gucnBtKSBiYTcxYzZlMWM1MmQwYzcwNzdjZGIyNWE1ODcwOWI4ZmI3YzM3YjM0NDE4YTgzMzhiYmY2NzY2ODMzOTY3NmQyMDhjMWE0ZmVmNGU1NDcwYzE1MmFhYzg0MDIwYjRjY2I4MDc0Y2UzODdkZTI0YmUzMzk3MTEyNTZjMGZhNzhjOAogICAgICAgICAgICBzZXQgaGFzaGVzKGY1LWFwcHN2Y3MtMy4xOC4wLTQubm9hcmNoLnJwbSkgZTcyZWU4MDA1YTI3MDcwYWMzOTlhYjA5N2U4YWE1MDdhNzJhYWU0NzIxZDc0OTE1ODljZmViODIxZGIzZWY4NmNiYzk3OWU3OTZhYjMxOWVjNzI3YmI1MTQwMGNjZGE4MTNjNGI5ZWI0YTZiM2QxMjIwYTM5NmI1ODJmOGY0MDAKICAgICAgICAgICAgc2V0IGhhc2hlcyhmNS1jbG91ZC1mYWlsb3Zlci0xLjEuMC0wLm5vYXJjaC5ycG0pIDE1YTQ0MGMyOTlmOWU0YWY4NmEzZDBmNWIwZDc1YjAwNTQzODViOTVlNDdjM2VmMTE2ZDJlMGJmYjAwNDFhMjZkY2JmNTQ5MDI4ZTJhMjZkMmM3MThlYzYxNDQ2YmQ2NTdiZTM4ZmJiY2Q5ZGI3ODFlZmU1NDE0YzE3NGFjNjhjCiAgICAgICAgICAgIHNldCBoYXNoZXMoZjUtY2xvdWQtZmFpbG92ZXItMS4zLjAtMC5ub2FyY2gucnBtKSAxOTY4MWViMzNkOWY5MTBjOTEzZjgxODAxOTk0ODVlYjY1M2I0YjVlYmVhYWUwYjkwYTZjZTgzNDFkN2EyMmZlZDhkMjE4MTViNWJhMTQ4YzQ2ODg1MmQyMGNjMjZmYWQ0YzQyNDJlNTBlY2MxODRmMWY4NzcwZGFjY2VkNmY2YQoKICAgICAgICAgICAgc2V0IGZpbGVfcGF0aCBbbGluZGV4ICR0bXNoOjphcmd2IDFdCiAgICAgICAgICAgIHNldCBmaWxlX25hbWUgW2ZpbGUgdGFpbCAkZmlsZV9wYXRoXQoKICAgICAgICAgICAgaWYgeyFbaW5mbyBleGlzdHMgaGFzaGVzKCRmaWxlX25hbWUpXX0gewogICAgICAgICAgICAgICAgdG1zaDo6bG9nIGVyciAiTm8gaGFzaCBmb3VuZCBmb3IgJGZpbGVfbmFtZSIKICAgICAgICAgICAgICAgIGV4aXQgMQogICAgICAgICAgICB9CgogICAgICAgICAgICBzZXQgZXhwZWN0ZWRfaGFzaCAkaGFzaGVzKCRmaWxlX25hbWUpCiAgICAgICAgICAgIHNldCBjb21wdXRlZF9oYXNoIFtsaW5kZXggW2V4ZWMgL3Vzci9iaW4vb3BlbnNzbCBkZ3N0IC1yIC1zaGE1MTIgJGZpbGVfcGF0aF0gMF0KICAgICAgICAgICAgaWYgeyAkZXhwZWN0ZWRfaGFzaCBlcSAkY29tcHV0ZWRfaGFzaCB9IHsKICAgICAgICAgICAgICAgIGV4aXQgMAogICAgICAgICAgICB9CiAgICAgICAgICAgIHRtc2g6OmxvZyBlcnIgIkhhc2ggZG9lcyBub3QgbWF0Y2ggZm9yICRmaWxlX3BhdGgiCiAgICAgICAgICAgIGV4aXQgMQogICAgICAgIH1dfSB7CiAgICAgICAgICAgIHRtc2g6OmxvZyBlcnIge1VuZXhwZWN0ZWQgZXJyb3IgaW4gdmVyaWZ5SGFzaH0KICAgICAgICAgICAgZXhpdCAxCiAgICAgICAgfQogICAgfQogICAgc2NyaXB0LXNpZ25hdHVyZSBuR0QveDZFOTZWakhzVVE0ZDM4ZExlZ1VORGFGU01IQWtLVmo3cDkwSU5mYjFXU0lsK0lhZnFOM0pRNGFGMVdQQk83VTFhNEs1Wjl4UGZkaUtaOXR3NnR5WVQzUlh1WjNqM2Z2RGpsN0pLYTcyZUNiNE5jTkFmaUU4M09Ya3R4WHE1LzJiMExmck5XNm83WnZTaGVveHpkM2w2eUlscFlqcmtndkNWektteEdrZis4Skh3RjNQWjMrOThMTmFMUWFJcmYyeDY3aU5RdUhvR0RObDNrOG9WMXRUcW9Zb2sya1Zwb2g3cmtvQXdRYXduOHBELyt1eTgzK2ZSd2ZwQ1JKRi81dVlzR0dheWZWOWhUWXhxdTJmN20zZER2YWJ3TzhpUkFjN1B1dUpNM1RQM2FmTmc5YkhlUG9WV2JEMUZLc2FjdW50QXBaWTlTeFpROTNGVVhLN0E9PQogICAgc2lnbmluZy1rZXkgL0NvbW1vbi9mNS1pcnVsZQp9\' | base64 -d > /config/verifyHash',
                                    'cat <<\'EOF\' > /config/waitThenRun.sh',
                                    '#!/bin/bash',
                                    'while true; do echo \"waiting for cloud libs install to complete\"',
                                    '    if [ -f /config/cloud/cloudLibsReady ]; then',
                                    '        break',
                                    '    else',
                                    '        sleep 10',
                                    '    fi',
                                    'done',
                                    '\"$@\"',
                                    'EOF',
                                    'cat <<\'EOF\' > /config/cloud/gce/collect-interface.sh',
                                    '#!/bin/bash',
                                    'COMPUTE_BASE_URL=\"http://metadata.google.internal/computeMetadata/v1\"',
                                    'echo "MGMTADDRESS=$(curl -s -f --retry 20 \'http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/1/ip\' -H \'Metadata-Flavor: Google\')" >> /config/cloud/gce/interface.config',
                                    'echo "MGMTMASK=$(curl -s -f --retry 20 \'http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/1/subnetmask\' -H \'Metadata-Flavor: Google\')" >> /config/cloud/gce/interface.config',
                                    'echo "MGMTGATEWAY=$(curl -s -f --retry 20 \'http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/1/gateway\' -H \'Metadata-Flavor: Google\')" >> /config/cloud/gce/interface.config',
                                    'echo "INT1ADDRESS=$(curl -s -f --retry 20 \'http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/ip\' -H \'Metadata-Flavor: Google\')" >> /config/cloud/gce/interface.config',
                                    'echo "INT1MASK=$(curl -s -f --retry 20 \'http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/subnetmask\' -H \'Metadata-Flavor: Google\')" >> /config/cloud/gce/interface.config',
                                    'echo "INT1GATEWAY=$(curl -s -f --retry 20 \'http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/gateway\' -H \'Metadata-Flavor: Google\')" >> /config/cloud/gce/interface.config',
                                    'echo "HOSTNAME=$(curl -s -f --retry 10 \"${COMPUTE_BASE_URL}/instance/hostname\" -H \'Metadata-Flavor: Google\')" >> /config/cloud/gce/interface.config',
                                    'CONFIG_FILE=\'/config/cloud/.deployment\'',
                                    'echo \'{"tagKey":"f5_deployment","tagValue":"' + context.env['deployment'] + '"}\' > $CONFIG_FILE',   
                                    'CLOUD_LIBS_DIR=\'/config/cloud/gce/node_modules/@f5devcentral\'',
                                    'chmod 755 /config/cloud/gce/interface.config',
                                    'reboot',
                                    'EOF',
                                    CFEJSON,
                                    'cat <<\'EOF\' > /config/cloud/gce/custom-config.sh',
                                    '#!/bin/bash',
                                    'source /usr/lib/bigstart/bigip-ready-functions',
                                    'wait_bigip_ready',
                                    'source /config/cloud/gce/interface.config',
                                    'MGMTNETWORK=$(/bin/ipcalc -n ${MGMTADDRESS} ${MGMTMASK} | cut -d= -f2)',
                                    'INT1NETWORK=$(/bin/ipcalc -n ${INT1ADDRESS} ${INT1MASK} | cut -d= -f2)',
                                    'PROGNAME=$(basename $0)',
                                    'function error_exit {',
                                    'echo \"${PROGNAME}: ${1:-\\\"Unknown Error\\\"}\" 1>&2',
                                    'exit 1',
                                    '}',
                                    'function wait_for_ready {',
                                    '   app=$1',
                                    '   checks=0',
                                    '   ready_response=""',
                                    '   ready_response_declare=""',
                                    '   checks_max=120',
                                    '   while [ $checks -lt $checks_max ] ; do',
                                    '      ready_response=$(curl -sku admin:$passwd -w "%{http_code}" -X GET  https://localhost:${mgmtGuiPort}/mgmt/shared/${app}/info -o /dev/null)',
                                    '      ready_response_declare=$(curl -sku admin:$passwd -w "%{http_code}" -X GET  https://localhost:${mgmtGuiPort}/mgmt/shared/${app}/declare -o /dev/null)',
                                    '      if [[ $ready_response == *200 ]] && [[ $ready_response_declare == *204 || $ready_response_declare == *200 ]]; then',
                                    '          echo "${app} is ready"',
                                    '          break',
                                    '      else',
                                    '         echo "${app}" is not ready: $checks, response: $ready_response $ready_response_declare',
                                    '         let checks=checks+1',
                                    '         if [[ $checks == $((checks_max/2)) ]]; then',
                                    '             echo "restarting restnoded"'
                                    '             bigstart restart restnoded',
                                    '         fi',
                                    '         sleep 15',
                                    '      fi',
                                    '   done',
                                    '   if [[ $ready_response != *200 ]] && [[ $ready_response_declare != *204 || $ready_response_declare != *200 ]]; then',
                                    '      error_exit "$LINENO: ${app} was not installed correctly. Exit."',
                                    '   fi',
                                    '}',
                                    'date',
                                    'declare -a tmsh=()',
                                    'echo \'starting custom-config.sh\'',
                                    'wait_bigip_ready',
                                    'tmsh+=(',
                                    '"tmsh load sys application template /config/cloud/f5.service_discovery.tmpl"',
                                    PHONEHOME,                                   
                                    '"tmsh modify sys global-settings mgmt-dhcp disabled"',
                                    '"tmsh delete sys management-route all"',
                                    '"tmsh delete sys management-ip all"',
                                    '"tmsh create sys management-ip ${MGMTADDRESS}/32"',
                                    '"tmsh create sys management-route mgmt_gw network ${MGMTGATEWAY}/32 type interface"',
                                    '"tmsh create sys management-route mgmt_net network ${MGMTNETWORK}/${MGMTMASK} gateway ${MGMTGATEWAY}"',
                                    '"tmsh create sys management-route default gateway ${MGMTGATEWAY}"',
                                    '"tmsh create net vlan external interfaces add { 1.0 } mtu 1460"',
                                    '"tmsh create net self self_external address ${INT1ADDRESS}/32 vlan external allow-service add { tcp:4353 udp:1026 }"',
                                    '"tmsh create net route ext_gw_interface network ${INT1GATEWAY}/32 interface external"',
                                    '"tmsh create net route ext_rt network ${INT1NETWORK}/${INT1MASK} gw ${INT1GATEWAY}"',
                                    '"tmsh create net route default gw ${INT1GATEWAY}"',
                                    '"tmsh modify cm device ${HOSTNAME} unicast-address { { effective-ip ${INT1ADDRESS} effective-port 1026 ip ${INT1ADDRESS} } }"',
                                    '"tmsh modify sys global-settings remote-host add { metadata.google.internal { hostname metadata.google.internal addr 169.254.169.254 } }"',
                                    '"tmsh modify sys db failover.selinuxallowscripts value enable"',
                                    '"tmsh modify sys management-dhcp sys-mgmt-dhcp-config request-options delete { ntp-servers }"',                                    
                                    '\'tmsh save /sys config\'',
                                    ')',
                                    'for CMD in "${tmsh[@]}"',
                                    'do',
                                    '    if $CMD;then',
                                    '        echo \"command $CMD successfully executed."',
                                    '    else',
                                    '        error_exit "$LINENO: An error has occurred while executing $CMD. Aborting!"',
                                    '    fi',
                                    'done',
                                    'date',
                                    '### START CUSTOM CONFIGURATION',
                                    'mgmtGuiPort="' + str(context.properties['mgmtGuiPort']) + '"',
                                    'passwd=$(f5-rest-node /config/cloud/gce/node_modules/@f5devcentral/f5-cloud-libs/scripts/decryptDataFromFile.js --data-file /config/cloud/gce/.adminPassword)',
                                    'file_loc="/config/cloud/custom_config"',
                                    'url_regex="(http:\/\/|https:\/\/)[a-z0-9]+([\-\.]{1}[a-z0-9]+)*\.[a-z]{2,5}(:[0-9]{1,5})?(\/.*)?$"',
                                    'if [[ ' + str(context.properties['declarationUrl']) + ' =~ $url_regex ]]; then',
                                    '   response_code=$(/usr/bin/curl -sk -w "%{http_code}" ' + str(context.properties['declarationUrl']) + ' -o $file_loc)',
                                    '   if [[ $response_code == 200 ]]; then',
                                    '       echo "Custom config download complete; checking for valid JSON."',
                                    '       cat $file_loc | jq .class',
                                    '       if [[ $? == 0 ]]; then',
                                    '           wait_for_ready appsvcs',
                                    '           response_code=$(/usr/bin/curl --retry 10 -skvvu admin:$passwd -w "%{http_code}" -X POST -H "Content-Type: application/json" https://localhost:${mgmtGuiPort}/mgmt/shared/appsvcs/declare -d @$file_loc -o /dev/null)',
                                    '           if [[ $response_code == *200 || $response_code == *502 ]]; then',
                                    '               echo "Deployment of custom application succeeded."',
                                    '           else',
                                    '               echo "Failed to deploy custom application; continuing..."',
                                    '           fi',
                                    '       else',
                                    '           echo "Custom config was not valid JSON, continuing..."',
                                    '       fi',
                                    '   else',
                                    '       echo "Failed to download custom config; continuing..."',
                                    '   fi',
                                    'else',
                                    '   echo "Custom config was not a URL, continuing..."',
                                    'fi',
                                    POSTCFE,
                                    '### END CUSTOM CONFIGURATION',
                                    'EOF',
                                    'cat <<\'EOF\' > /config/cloud/gce/rm-password.sh',
                                    '#!/bin/bash',
                                    'date',
                                    'source /config/cloud/gce/interface.config',
                                    'echo \'starting rm-password.sh\'',
                                    SYNC,
                                    'rm /config/cloud/gce/.adminPassword',
                                    'tmsh save /sys config',
                                    'date',
                                    'EOF', 
                                    CREATEVA,
                                    'curl -s -f --retry 20 -o /config/cloud/f5-cloud-libs.tar.gz https://cdn.f5.com/product/cloudsolutions/f5-cloud-libs/v4.20.0/f5-cloud-libs.tar.gz',
                                    'curl -s -f --retry 20 -o /config/cloud/f5-cloud-libs-gce.tar.gz https://cdn.f5.com/product/cloudsolutions/f5-cloud-libs-gce/v2.4.0/f5-cloud-libs-gce.tar.gz',
                                    'curl -s -f --retry 20 -o /config/cloud/f5-appsvcs-3.18.0-4.noarch.rpm https://cdn.f5.com/product/cloudsolutions/f5-appsvcs-extension/v3.18.0/f5-appsvcs-3.18.0-4.noarch.rpm',
                                    'curl -s -f -L --retry 20 -o /config/cloud/f5-cloud-failover-1.3.0-0.noarch.rpm https://github.com/F5Networks/f5-cloud-failover-extension/releases/download/v1.3.0/f5-cloud-failover-1.3.0-0.noarch.rpm',
                                    'curl -s -f --retry 20 -o /config/cloud/f5.service_discovery.tmpl https://cdn.f5.com/product/cloudsolutions/iapps/common/f5-service-discovery/v2.3.2/f5.service_discovery.tmpl',
                                    'chmod 755 /config/verifyHash',
                                    'chmod 755 /config/installCloudLibs.sh',
                                    'chmod 755 /config/waitThenRun.sh',
                                    'chmod 755 /config/cloud/gce/collect-interface.sh',
                                    'chmod 755 /config/cloud/gce/custom-config.sh',
                                    'chmod 755 /config/cloud/gce/rm-password.sh',
                                    'chmod 755 /config/cloud/gce/create-va.sh',
                                    'mkdir -p /var/log/cloud/google',
                                    CUSTHASH,
                                    'touch /config/cloud/gce/FIRST_BOOT_COMPLETE',
                                    'nohup /usr/bin/setdb provision.1nicautoconfig disable &>> /var/log/cloud/google/install.log < /dev/null &',
                                    'nohup /config/installCloudLibs.sh &>> /var/log/cloud/google/install.log < /dev/null &',
                                    'nohup /config/waitThenRun.sh f5-rest-node /config/cloud/gce/node_modules/@f5devcentral/f5-cloud-libs/scripts/runScript.js --file f5-rest-node --cl-args \'/config/cloud/gce/node_modules/@f5devcentral/f5-cloud-libs/scripts/generatePassword --file /config/cloud/gce/.adminPassword --encrypt\' --signal GENERATE_PASSWORD_DONE --log-level ' + str(context.properties['logLevel']) + ' --output /var/log/cloud/google/generatePassword.log 2>&1 >> /var/log/cloud/google/install.log < /dev/null &',
                                    'nohup /config/waitThenRun.sh f5-rest-node /config/cloud/gce/node_modules/@f5devcentral/f5-cloud-libs/scripts/runScript.js --file /config/cloud/gce/node_modules/@f5devcentral/f5-cloud-libs/scripts/createUser.sh --cl-args \'--user admin --password-file /config/cloud/gce/.adminPassword --password-encrypted\' --signal CREATE_USER_DONE --wait-for GENERATE_PASSWORD_DONE --log-level ' + str(context.properties['logLevel']) + ' --output /var/log/cloud/google/createUser.log 2>&1 >> /var/log/cloud/google/install.log < /dev/null &',
                                    'nohup /config/waitThenRun.sh f5-rest-node /config/cloud/gce/node_modules/@f5devcentral/f5-cloud-libs/scripts/onboard.js --db provision.managementeth:eth1 --host localhost -o /var/log/cloud/google/mgmt-swap.log --log-level ' + str(context.properties['logLevel']) + ' --wait-for CREATE_USER_DONE --signal MGMT_SWAP_DONE >> /var/log/cloud/google/install.log < /dev/null &',
                                    'nohup /config/waitThenRun.sh f5-rest-node /config/cloud/gce/node_modules/@f5devcentral/f5-cloud-libs/scripts/runScript.js --file /config/cloud/gce/collect-interface.sh --cwd /config/cloud/gce -o /var/log/cloud/google/interface-config.log --wait-for MGMT_SWAP_DONE --log-level ' + str(context.properties['logLevel']) + ' >> /var/log/cloud/google/install.log < /dev/null &',
                                    'else',
                                    'source /config/cloud/gce/interface.config',
                                    'nohup /config/waitThenRun.sh f5-rest-node /config/cloud/gce/node_modules/@f5devcentral/f5-cloud-libs/scripts/onboard.js -o /var/log/cloud/google/onboard.log --log-level ' + str(context.properties['logLevel']) + ' --signal ONBOARD_DONE --install-ilx-package file:///config/cloud/f5-appsvcs-3.18.0-4.noarch.rpm --install-ilx-package file:///config/cloud/f5-cloud-failover-1.3.0-0.noarch.rpm --host localhost --no-reboot --user admin --password-url file:///config/cloud/gce/.adminPassword --password-encrypted --port 443 --ssl-port ' + str(context.properties['mgmtGuiPort']) + ' --hostname $HOSTNAME ' + ntp_list + timezone + ' --modules ' + PROVISIONING_MODULES + SENDANALYTICS + ' 2>&1 >> /var/log/cloud/google/install.log < /dev/null &',
                                    'nohup /config/waitThenRun.sh f5-rest-node /config/cloud/gce/node_modules/@f5devcentral/f5-cloud-libs/scripts/runScript.js --file /config/cloud/gce/custom-config.sh --cwd /config/cloud/gce --wait-for ONBOARD_DONE --signal CUSTOM_CONFIG_DONE --log-level ' + str(context.properties['logLevel']) + ' -o /var/log/cloud/google/custom-config.log 2>&1 >> /var/log/cloud/google/install.log < /dev/null &',
                                    CLUSTERJS,
                                    RUNCREATEVA,
                                    'touch /config/startupFinished',
                                    'fi'
                                    ])
                            )
                }]
    }
  return metadata

def Instance(context, group, storageName, licenseType, device, avZone, network1SharedVpc):
  aliasIps = []
  accessConfigSubnet = []
  accessConfigMgmt = []
  tagItems = ['mgmtfw-' + context.env['deployment'], 'extfw-' + context.env['deployment']]
  provisionPublicIp = str(context.properties['provisionPublicIP']).lower()

  # access config and tags - conditional on provisionPublicIP parameter (yes/no)
  if provisionPublicIp in ['yes', 'true']:
    accessConfigSubnet = [{
       'name': 'Subnet 1 NAT',
       'type': 'ONE_TO_ONE_NAT'
    }]
    accessConfigMgmt = [{
      'name': 'Management NAT',
      'type': 'ONE_TO_ONE_NAT'
    }]
  else:
    tagItems.append('no-ip')

  if group == 'join' and str(context.properties['aliasIp']).lower() != 'none':
    aliasIps = [{'ipCidrRange': ip} for ip in context.properties['aliasIp'].split(';')]

  # Build instance template
  instance = {
        'zone': avZone,
        'canIpForward': True,
        'tags': {
          'items': tagItems
        },
        'hostname': ''.join(['bigip', device, '-', context.env['deployment'], '.c.', context.env['project'], '.internal']),
        'labels': {
          'f5_deployment': context.env['deployment'],
          'f5_cloud_failover_label': context.env['deployment']
        },
        'machineType': ''.join([COMPUTE_URL_BASE, 'projects/',
                         context.env['project'], '/zones/', avZone, '/machineTypes/',
                         context.properties['instanceType']]),
        'serviceAccounts': [{
            'email': context.properties['serviceAccount'],
            'scopes': ['https://www.googleapis.com/auth/compute','https://www.googleapis.com/auth/devstorage.read_write']
        }],
        'disks': [{
            'deviceName': 'boot',
            'type': 'PERSISTENT',
            'boot': True,
            'autoDelete': True,
            'initializeParams': {
                'sourceImage': ''.join([COMPUTE_URL_BASE, 'projects/f5-7626-networks-public',
                                    '/global/images/',
                                    context.properties['imageName'],
                                ])
            }
        }],
        'networkInterfaces': [{
            'network': ''.join([COMPUTE_URL_BASE, 'projects/',
                            network1SharedVpc, '/global/networks/',
                            context.properties['network1']]),
            'subnetwork': ''.join([COMPUTE_URL_BASE, 'projects/',
                            network1SharedVpc, '/regions/',
                            context.properties['region'], '/subnetworks/',
                            context.properties['subnet1']]),
            'accessConfigs': accessConfigSubnet,
            'aliasIpRanges': aliasIps
          },
          {
            'network': ''.join([COMPUTE_URL_BASE, 'projects/',
                            context.env['project'], '/global/networks/',
                            context.properties['mgmtNetwork']]),
            'subnetwork': ''.join([COMPUTE_URL_BASE, 'projects/',
                            context.env['project'], '/regions/',
                            context.properties['region'], '/subnetworks/',
                            context.properties['mgmtSubnet']]),
            'accessConfigs': accessConfigMgmt
          }],
          'metadata': Metadata(context, group, storageName, licenseType)
    }
  return instance
def ForwardingRule(context, name, target):
  # Build forwarding rule
  forwardingRule = {
        'name': name,
        'type': 'compute.v1.forwardingRule',
        'properties': {
            'region': context.properties['region'],
            'IPProtocol': 'TCP',
            'target': target,
            'loadBalancingScheme': 'EXTERNAL',
        }
  }
  return forwardingRule

def Outputs(context):
    output_ip_options = {
        'public': '.accessConfigs[0].natIP',
        'private': '.networkIP'
    }
    pub_or_priv = 'public' if str(context.properties['provisionPublicIP']).lower() in ['yes', 'true'] else 'private'

    outputs = [{
        'name': 'region',
        'value': context.properties['region']
    },
    {
        'name': 'mgmtURL1',
        'value': 'https://$(ref.bigip1-' + context.env['deployment'] + '.networkInterfaces[1]' + output_ip_options[pub_or_priv] + '):' + str(context.properties['mgmtGuiPort'])
    },
    {
        'name': 'mgmtURL2',
        'value': 'https://$(ref.bigip2-' + context.env['deployment'] + '.networkInterfaces[1]' + output_ip_options[pub_or_priv] + '):' + str(context.properties['mgmtGuiPort'])
    }]
    return outputs

def ForwardingRuleOutputs(context, numberPostfix):
    forwardingRuleOutputs = {
        'name': 'appTrafficAddress' + numberPostfix,
        'value': '$(ref.' + context.env['deployment'] + '-fr' + numberPostfix + '.IPAddress)'
    }
    return forwardingRuleOutputs

def GenerateConfig(context):

  ## set variables
  # Set project names for networks
  network1SharedVpc = context.env['project']
  if str(context.properties['network1SharedVpc']).lower() != 'none':
      network1SharedVpc = context.properties['network1SharedVpc']
  storageName = 'f5-bigip-storage-' + context.env['deployment']
  instanceName0 = 'bigip1-' + context.env['deployment']
  instanceName1 = 'bigip2-' + context.env['deployment']
  fwdRulesNamePrefix = context.env['deployment'] + '-fr'
  forwardingRules = []
  forwardingRuleOutputs = []
  for i in list(range(int(context.properties['numberOfForwardingRules']))):
    forwardingRules = forwardingRules + [ForwardingRule(context, fwdRulesNamePrefix + str(i), '$(ref.' + instanceName1 + '-ti.selfLink)')]
    forwardingRuleOutputs = forwardingRuleOutputs + [ForwardingRuleOutputs(context, str(i))]

  resources = [
  FirewallRuleMgmt(context),
  {
    'name': instanceName0,
    'type': 'compute.v1.instance',
    'properties': Instance(context, 'create', storageName, 'payg', '1', context.properties['availabilityZone1'], network1SharedVpc)
  },{
    'name': instanceName1,
    'type': 'compute.v1.instance',
    'properties': Instance(context, 'join', storageName, 'payg', '2', context.properties['availabilityZone2'], network1SharedVpc)
  },{
    'name': storageName,
    'type': 'storage.v1.bucket',
    'properties': {
      'project': context.env['project'],
      'name': storageName,
      'labels': {
        'f5_cloud_failover_label': context.env['deployment']
      },
    },
  },{
    'name': instanceName0 + '-ti',
    'type': 'compute.v1.targetInstances',
    'properties': {
      'description': instanceName0,
      'natPolicy': 'NO_NAT',
      'zone': context.properties['availabilityZone1'],
      'instance': ''.join([COMPUTE_URL_BASE, 'projects/', context.env['project'], '/zones/',
                          context.properties['availabilityZone1'], '/instances/', instanceName0])
    }
  },{
    'name': instanceName1 + '-ti',
    'type': 'compute.v1.targetInstances',
    'properties': {
      'description': instanceName1,
      'natPolicy': 'NO_NAT',
      'zone': context.properties['availabilityZone2'],
      'instance': ''.join([COMPUTE_URL_BASE, 'projects/', context.env['project'], '/zones/',
                          context.properties['availabilityZone2'], '/instances/', instanceName1])
    }
  }]
  if network1SharedVpc == context.env['project']:
    resources = resources + [{
      'name': 'extfirewall-' + context.env['deployment'],
      'type': 'compute.v1.firewall',
      'properties': {
          'network': ''.join([COMPUTE_URL_BASE, 'projects/',
                              network1SharedVpc, '/global/networks/',
                              context.properties['network1']]),
          'targetTags': ['extfw-'+ context.env['deployment']],
          'sourceTags': ['extfw-'+ context.env['deployment']],
          'allowed': [{
              'IPProtocol': 'TCP',
              'ports': [4353]
              },{
              'IPProtocol': 'UDP',
              'ports': [1026],
          }]
        }
      }]
  # add forwarding rules
  resources = resources + forwardingRules
  outputs = Outputs(context)
  outputs = outputs + forwardingRuleOutputs
  return {'resources': resources, 'outputs': outputs}