import os, sys, platform
from subprocess import Popen, PIPE
import argparse

sys.path.append('/usr/lib/vmware-vpx/vsan-health/')
sys.path.append('/usr/lib/vmware-vpx/pyJack/')
sys.path.append('/usr/lib/vmware/site-packages/')
import pyVmomi
from pyVmomi import vim, vmodl, VmomiSupport, SoapStubAdapter
import pyVim
from pyVim import connect
import vsanmgmtObjects
import http.cookies
from pyVim.task import WaitForTask
import json
import time
import uuid
import six.moves.http_cookies

def GetArgs():
   """
   Supports the command-line arguments listed below.
   """
   parser = argparse.ArgumentParser(
       description='Process args for vSAN SDK sample application')
   parser.add_argument('-i', '--vc', required=True, action='store',
                       help='IP of vCenter')
   parser.add_argument('-u', '--user', required=True, action='store',
                       help='User name to use when connecting to host')
   parser.add_argument('-p', '--password', required=False, action='store',
                       help='Password to use when connecting to host')
   parser.add_argument('-c', '--clusterName', required=True, action='store',
                       help='Cluster Name for the hosts')
   parser.add_argument('-dc', '--datacenterName', required=True, action='store',
                       help='Datacenter Name for the VC')
   parser.add_argument('-ips', '--hostIps', required=True, action='store',
                       help='IPs of the hosts to be added to the cluster,\
                             The IPs of the hosts, splitted by commar')
   parser.add_argument('-hu', '--hostUsername', required=True, action='store',
                       help='Username of the hosts')
   parser.add_argument('-hp', '--hostPassword', required=True, action='store',
                       help='Password of the hosts')
   args = parser.parse_args()
   return args

# This script is supposed to be run in the shell of vCenter
if __name__ == '__main__':
    vch = platform.node()
    args = GetArgs()
    version = pyVmomi.VmomiSupport.newestVersions.GetName('vim')
    si = pyVim.connect.Connect(host=vch, user=args.user, pwd=args.password, version=version)
    stub = si._stub
    sc = si.RetrieveContent()

     # Create datacenter
    notfound = True
    searchIndex = sc.searchIndex
    datacenters = sc.rootFolder.childEntity
    for datacenter in datacenters:
      if args.datacenterName in datacenter.name:
            dcRef = datacenter
            notfound = False
    if notfound:
       dcRef = sc.rootFolder.CreateDatacenter(name=args.datacenterName)
    
    vsanEnabledClientClusterName1 = args.clusterName
    clusterSpec = vim.cluster.ConfigSpecEx()
    serverClusterRef = dcRef.hostFolder.CreateClusterEx(name=vsanEnabledClientClusterName1, spec=clusterSpec)


    def _addHostToCluster(clusterRef, hostname, username, password):
        def _getsslThumbprint(ip):
            p1 = Popen(('echo', '-n'),
                       stdout=PIPE, stderr=PIPE)
            p2 = Popen(('openssl', 's_client', '-connect', '{0}:443'.format(ip)),
                       stdin=p1.stdout, stdout=PIPE, stderr=PIPE)
            p3 = Popen(('openssl', 'x509', '-noout', '-fingerprint', '-sha1'),
                       stdin=p2.stdout, stdout=PIPE, stderr=PIPE)
            out = p3.stdout.read().decode("utf-8")
            sslThumbprint = out.split('=')[-1].strip()
            return sslThumbprint

        esxsslthumbprint = _getsslThumbprint(hostname)
        hostspec = vim.host.ConnectSpec(hostName=hostname,
                                        userName=username,
                                        sslThumbprint=esxsslthumbprint,
                                        password=password,
                                        force=True)
        WaitForTask(clusterRef.AddHost(spec=hostspec,
                                       asConnected=True))

    #Add esx now, repeat for number of esx
    hostIps = args.hostIps.split(',')
    for hostIp in hostIps:
        _addHostToCluster(serverClusterRef, hostIp, args.hostUsername, args.hostPassword)

    def _vpxdStub2HelathStub(stub):
        version1 = pyVmomi.VmomiSupport.newestVersions.Get("vsan")
        sessionCookie = stub.cookie.split('"')[1]
        httpContext = pyVmomi.VmomiSupport.GetHttpContext()
        cookieObj = http.cookies.SimpleCookie()
        cookieObj["vmware_soap_session"] = sessionCookie
        httpContext["cookies"] = cookieObj
        hostname = stub.host.split(":")[0]
        vhStub = pyVmomi.SoapStubAdapter(host=hostname, version=version1, path="/vsanHealth", poolSize=0)
        vhStub.cookie = stub.cookie
        return vhStub

    # Connect to vSAN endpoint
    stub = si._stub
    VmomiSupport.AddVersionParent('vsan.version.version21', 'vim.version.VSAN2_Configure')
    VmomiSupport.AddVersionParent('vsan.version.version21', 'vim.version.unstable')
    vhstub = _vpxdStub2HelathStub(stub)

    # Read current cluster config
    vcs = vim.cluster.VsanVcClusterConfigSystem('vsan-cluster-config-system', vhstub)
    print(serverClusterRef.name, " - Current cluser config:")
    print(vcs.GetConfigInfoEx(serverClusterRef))

    print('=== Enable storage only mode ===')
    STORAGE_MODE = 'Mode_Storage'
    rs = vim.Vsan.ReconfigSpec(vsanClusterConfig=vim.vsan.cluster.ConfigInfo(enabled=True, vsanEsaEnabled=True), 
                               mode=vim.Vsan.Mode(STORAGE_MODE))
    tsk = vcs.ReconfigureEx(serverClusterRef, rs)
    tsk = vim.Task(tsk._moId, serverClusterRef._stub)
    WaitForTask(tsk)
    print("Reconfig task info:")
    print(tsk.info)
    print("Current cluster config:")
    print(vcs.GetConfigInfoEx(serverClusterRef))
  
