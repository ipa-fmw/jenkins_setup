#!/usr/bin/env python

import sys
import os
import subprocess
import traceback
import paramiko
import urllib2
import yaml
import optparse

ARCH = ['i386', 'amd64']


def pbuilder_create(basetgz, tarball_dir, dist, arch):
    command = "sudo pbuilder --create --basetgz " + tarball_dir + "/" + basetgz + " --distribution " + dist + " --architecture " + arch
    command = command.split(' ') + ["--components","main restricted universe multiverse"]
    ret_pbuilder = subprocess.call(command)
    if ret_pbuilder != 0:
        print "pbuilder create failed for", basetgz
        return ret_pbuilder
    return 0
    

def pbuilder_execute(basetgz, tarball_dir, script):
    command = "sudo pbuilder --execute --basetgz " + tarball_dir + "/" + basetgz + " --save-after-exec -- " + script
    return call(command)



def main():
    """
    Set up and update all chroot tarballs
    """

    errors = []

    # parse options
    parser = optparse. OptionParser()
    (options, args) = parser.parse_args()

    if len(args) < 4:
        print "Usage: %s tarball_location_ssh_address target_yaml_url ubuntu_distro architecture [apt_cacher_proxy_address]" % (sys.argv[0])
        sys.exit()

    print args

    tarball_location_ssh_address = args[0]
    target_platforms_url = args[1]

    tarball_host = tarball_location_ssh_address.split(':')[0].split('@')[1]
    tarball_host_username = tarball_location_ssh_address.split('@')[0]
    tarball_dir = tarball_location_ssh_address.split(':')[1]

    try:
        f = urllib2.urlopen(target_platforms_url)
        platforms = yaml.load(f)
    except Exception as ex:
        print "While downloading and parsing target platforms file from\n%s\n \
               the following error occured:\n%s" % (target_platforms_url, ex)
        raise ex

    # check if given ubuntu distro and arch is supported
    ubuntu_distro = args[2]
    supported_ubuntu_distros = []
    for ros_distro_dict in platforms:
        for ros_distro, ubuntu_distro_list in ros_distro_dict.iteritems():
            for supported in ubuntu_distro_list:
                if supported not in supported_ubuntu_distros:
                    supported_ubuntu_distros.append(supported)
    if ubuntu_distro not in supported_ubuntu_distros:
        print "Ubuntu distro %s not supported! Supported Ubuntu distros :" % ubuntu_distro, ', '.join(sorted(supported_ubuntu_distros))
        sys.exit()
    arch = args[3]
    if arch not in ARCH:
        print "Architecture %s not supported! Supported architectures: %s" % (arch, ', '.join(ARCH))
        sys.exit()

    apt_cacher_proxy = ''
    if len(args) == 5:
        apt_cacher_proxy = args[4]

    # set up ssh object
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(tarball_host, username=tarball_host_username)

    # get home folder
    if tarball_dir.startswith('~/'):
        tarball_dir = tarball_dir.replace('~/', '')
    if not tarball_dir.startswith('/'):
        tarball_dir = os.path.join(get_home_folder(ssh), tarball_dir)

    print "\nGet existent chroot tarballs"
    existent_tarballs = get_existent_tarballs(ssh, tarball_dir)
    for tar in existent_tarballs:
        print " ", tar

    print "\nCalculate chroot envs to set up / update"
    basic_tarball, extended_tarballs = get_tarball_names(platforms, ubuntu_distro, arch)
    print "Basic tarball:"
    print " ", basic_tarball
    print "Extended tarballs: \n %s" % '\n '.join(extended_tarballs)
    print ""

    sys.stdout.flush()

    print "\nvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv"
    print "Set up basic chroot %s" % basic_tarball
    #result = process_basic_tarball(ssh, basic_tarball, os.getenv("WORKSPACE"),
    #                               tarball_dir, extended_tarballs, existent_tarballs,
    #                               apt_cacher_proxy)
    
    
    
    # create basic tarball
    tarball_params = get_tarball_params(basic_tarball)
    print "tarball parameter: ", tarball_params
    ret = pbuilder_create(basic_tarball, tarball_dir, tarball_params['ubuntu_distro'], tarball_params['arch'])
    if ret != 0:
        print "Creation of basic tarball failed: ", basic_tarball
        call("rm -rf "+ tarball_dir + "/" + basic_tarball)
        sys.exit(1)
    else:
        print "Successful creation of basic tarball: ", basic_tarball
        # change ownership of tarball
        command = "sudo chown jenkins:jenkins " + tarball_dir + "/" + basic_tarball
        call(command)
    
    # create extended tarballs 
    failed_tarballs = []
    for tarball in extended_tarballs:
        tarball_params = get_tarball_params(tarball)
        print "tarball parameter: ", tarball_params
        call("cp " + tarball_dir + "/" + basic_tarball + " " + tarball_dir + "/" + tarball)
        ret = pbuilder_execute(tarball, tarball_dir, "./install_basics.sh " + tarball_params['ubuntu_distro'] + " " + tarball_params['ros_distro'] + " " + apt_cacher_proxy)
        if ret != 0:
            print "Creation of extended tarball failed: ", tarball
            call("rm -rf "+ tarball_dir + "/" + tarball)
            failed_tarballs.append(tarball)
        else:
            print "Successful creation of extended tarball: ", tarball
            # change ownership of tarballs
            command = "sudo chown jenkins:jenkins " + tarball_dir + "/" + tarball
            call(command)

    if len(failed_tarballs) != 0:
        print "Not all tarballs were generated successfully. Failed tarballs: ", failed_tarballs
        sys.exit(1)
    
    sys.exit()
 

def put_tarball(ssh, tar_name, from_location, to_location):
    print "Copying %s to %s" % (tar_name, ssh.get_host_keys().keys()[0])
    sys.stdout.flush()
    try:
        ftp = ssh.open_sftp()
        ftp.put(from_location,
                to_location)
    except Exception as ex:
        print ex
        raise Exception(ex)
    finally:
        ftp.close()
    print "Copied successfully %s to %s" % (tar_name, ssh.get_host_keys().keys()[0])
    sys.stdout.flush()


def get_home_folder(ssh):
    stdin, stdout, stderr = ssh.exec_command("pwd")
    return stdout.readline().replace('\n', '')


def get_existent_tarballs(ssh, path):
    file_list = []
    stdin, stdout, stderr = ssh.exec_command("ls -1 %s" % path)
    for line in stdout.readlines():
        line = line.replace('\n', '')
        file_list.append(line)
    return file_list


def get_tarball_params(name):
    params_dict = {}
    name_split = name.split('__')
    if len(name_split) == 2:
        params_dict['ubuntu_distro'], params_dict['arch'] = name_split
        params_dict['ros_distro'] = None
    elif len(name_split) == 3:
        params_dict['ubuntu_distro'], params_dict['arch'], params_dict['ros_distro'] = name_split
    else:
        raise BuildException('Invalid tarball name')
    return params_dict


def get_tarball_names(platforms, ubuntu_distro, arch):
    basic_tarball = '__'.join([ubuntu_distro, arch])
    extended_tarballs = []
    for ros_distro_dict in platforms:
        for ros_distro, ubuntu_distro_list in ros_distro_dict.iteritems():
            if ubuntu_distro in ubuntu_distro_list and ros_distro != "backports":
                extended_tarballs.append('__'.join([ubuntu_distro, arch,
                                                    ros_distro]))
    return basic_tarball, sorted(extended_tarballs)


def call_with_list(command, envir=None, verbose=False):
    """
    Call a shell command as list.

    @param command: the command to call
    @type  command: list
    @param envir: mapping of env variables
    @type  envir: dict
    @param verbose: print all
    @type  verbose: bool

    @return param: command output
    @return type: str

    @raise type: BuildException
    """
    print "Executing command '%s'" % ' '.join(command)
    return subprocess.call(command)
    #helper = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True, env=envir)


def call(command, envir=None, verbose=True):
    return call_with_list(command.split(' '), envir, verbose)


class BuildException(Exception):
    def __init__(self, msg):
        self.msg = msg


if __name__ == "__main__":
    try:
        result = main()

    except Exception as ex:
        print traceback.format_exc()
        print "\n,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,"
        print "Update script failed. Check console output for details."
        print "'''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''\n"
        raise ex
