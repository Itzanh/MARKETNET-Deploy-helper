import json
import os
import zipfile
from os import path

import requests

OCTOPUS_URL = ""
OCTOPUS_HEADERS = {'X-Octopus-ApiKey': ''}
projects = []
selected_packages = []


class OctopusRelease:
    def __init__(self, version, channel_id, project_id, selected_packages, space_id):
        self.Version = version
        self.ChannelId = channel_id
        self.ProjectId = project_id
        self.SelectedPackages = selected_packages
        self.SpaceId = space_id


class OctopusSelectedPackage:
    def __init__(self, step_name, action_name, version):
        self.StepName = step_name
        self.ActionName = action_name
        self.Version = version


class OctopusDeployment:
    def __init__(self, release_id, channel_id, environment_id, project_id):
        self.ReleaseId = release_id
        self.ChannelId = channel_id
        self.EnvironmentId = environment_id
        self.ProjectId = project_id


class ZipInfo:
    def __init__(self, zip_what, exclude):
        self.zip_what = zip_what
        self.exclude = exclude


class DeployablePojects:
    def __init__(self, id, name, project_path, do_deploy, channel_id, project_id, space_id, step_name, action_name,
                 single_selected_package_name, environment_id, git_repos, prepare_deploy_steps, zip, package_file_name,
                 clean_up_steps):
        self.id = id
        self.name = name
        self.project_path = project_path
        self.do_deploy = do_deploy
        # Octopus Deploy Release
        self.channel_id = channel_id
        self.project_id = project_id
        self.space_id = space_id
        self.step_name = step_name
        self.action_name = action_name
        self.single_selected_package_name = single_selected_package_name
        self.environment_id = environment_id
        # Git
        self.git_repos = git_repos
        # Deploy
        self.prepare_deploy_steps = prepare_deploy_steps
        self.zip = zip
        self.package_file_name = package_file_name
        # Clean up
        self.clean_up_steps = clean_up_steps

    def git(self):
        commit_message = ""
        while commit_message == "":
            print("Input the commit message for: " + self.name)
            commit_message = input()
        os.chdir(self.project_path)
        os.system("git add .")
        os.system("git commit -m {0}".format(commit_message))
        for repo in self.git_repos:
            os.system("git push {0} master".format(repo))

    def deploy(self):
        version, next_version = self._get_latest_release_number()
        print("Input the next version code: {0} [{1}]".format(self.name, next_version))
        _next_version = input()
        if _next_version == "":
            _next_version = next_version

        self._build_package(_next_version)
        if not self._zip(_next_version):
            return False
        if not self._upload_package(_next_version):
            return False
        create_release_ok, octopus_release_id = self._create_release(next_version)
        if not create_release_ok:
            return False
        if not self._deploy_release(octopus_release_id):
            return False
        self._clean_up(next_version)
        return True

    def _get_latest_release_number(self):
        response = requests.get("{0}projects/{1}/releases".format(OCTOPUS_URL, self.project_id),
                                headers=OCTOPUS_HEADERS)
        octopus_releases = json.loads(response.text)
        version = octopus_releases['Items'][0]['Version']
        # Get next release number
        version_code = version.split('.')
        version_code[len(version_code) - 1] = str(int(version_code[len(version_code) - 1]) + 1)
        next_version = '.'.join(version_code)

        return version, next_version

    def _build_package(self, next_version):
        print(self.name + ": BUILDING PACKAGE")
        os.chdir(self.project_path)
        for cmd in self.prepare_deploy_steps:
            os.system(cmd.format(next_version))

    def _zip(self, next_version):
        if self.zip is None:
            return
        print(self.name + ": CREATING ZIP")
        zip_file_name = self.package_file_name.format(next_version)
        zip_file = zipfile.ZipFile(zip_file_name, 'w', zipfile.ZIP_DEFLATED)
        zip_path = path.join(self.project_path, self.zip.zip_what)
        print(self.project_path)
        print(self.zip.zip_what)
        print(zip_path)
        for root, dirs, files in os.walk(zip_path):
            dirs[:] = [d for d in dirs if d not in self.zip.exclude]
            for file in files:
                if (file not in self.zip.exclude) and (file != zip_file_name):
                    zip_file.write(path.join(root, file), path.relpath(path.join(root, file), zip_path))
        zip_file.close()
        return True

    def _upload_package(self, next_version):
        print(self.name + ": UPLOADING PACKAGE")
        package_name = self.package_file_name.format(next_version)
        with open(path.join(self.project_path, package_name), 'rb') as package:
            uri = '{0}{1}/packages/raw?replace=false'.format(OCTOPUS_URL, self.space_id)
            files = {
                'fileData': (package_name, package, 'multipart/form-data', {'Content-Disposition': 'form-data'})
            }

            response = requests.post(uri, headers=OCTOPUS_HEADERS, files=files)
            if response.status_code < 200 or response.status_code > 299:
                print("Octopus returned an error uploading the package!!! " + str(response.status_code))
                return False
            else:
                return True

    def _create_release(self, next_version):
        print(self.name + ": CREATE RELEASE")
        if self.single_selected_package_name == "":
            selected_package = OctopusSelectedPackage(self.step_name, self.action_name, next_version)
        else:
            selected_package = OctopusSelectedPackage(self.single_selected_package_name,
                                                      self.single_selected_package_name, next_version)

        selected_packages.append(selected_package)
        release = OctopusRelease(next_version, self.channel_id, self.project_id,
                                 list(map(lambda sel_pack: sel_pack.__dict__, selected_packages)), self.space_id)

        uri = '{0}releases'.format(OCTOPUS_URL)
        response = requests.post(uri, headers=OCTOPUS_HEADERS, data=json.dumps(release.__dict__))
        if response.status_code < 200 or response.status_code > 299:
            print("Octopus returned an error creating the release!!! " + str(response.status_code))
            print(response.text)
            return False, ""

        if self.single_selected_package_name != "":
            selected_package.ActionName = self.action_name
            selected_package.StepName = self.step_name
            selected_packages.pop()
            selected_packages.append(selected_package)

        octopus_release_returned = json.loads(response.text)

        return True, octopus_release_returned['Id']

    def _deploy_release(self, octopus_release_id):
        if not self.do_deploy:
            print(self.name + ": SKIPPING DEPLOY")
            return True
        print(self.name + ": DEPLOYING...")
        deployment = OctopusDeployment(octopus_release_id, self.channel_id, self.environment_id, self.project_id)
        uri = '{0}{1}/deployments'.format(OCTOPUS_URL, self.space_id)
        response = requests.post(uri, headers=OCTOPUS_HEADERS, data=json.dumps(deployment.__dict__))
        if response.status_code < 200 or response.status_code > 299:
            print("Octopus returned an error DEPLOYING the release!!! " + str(response.status_code))
            print(response.text)
            return False
        return True

    def _clean_up(self, next_version):
        print(self.name + ": CLEANING UP")
        os.chdir(self.project_path)
        for cmd in self.clean_up_steps:
            os.system(cmd.format(next_version))


def load_settings():
    with open('config.json') as json_file:
        config = json.load(json_file)
    global OCTOPUS_URL
    OCTOPUS_URL = config['octopus_url']
    global OCTOPUS_HEADERS
    OCTOPUS_HEADERS = {'X-Octopus-ApiKey': config['octopus_api_key']}


def load_projects():
    with open('projects.json') as json_file:
        _projects = json.load(json_file)
    for p in _projects:
        zip = ZipInfo(p['zip']['zip_what'], p['zip']['exclude'])

        projects.append(
            DeployablePojects(p['id'], p['name'], p['project_path'], p['deploy'], p['channel_id'], p['project_id'],
                              p['space_id'], p['step_name'], p['action_name'], p['single_selected_package_name'],
                              p['environment_id'], p['git_repos'], p['prepare_deploy_steps'], zip,
                              p['package_file_name'], p['clean_up_steps']))
    projects.sort(key=lambda project: project.id, reverse=False)


def main():
    load_settings()
    load_projects()
    print("PROJECTS THAT WILL BE DEPLOYED:")
    for i in range(len(projects)):
        print(str(i) + ": " + projects[i].name)
    print("Press ENTER to continue")
    input()
    do_git = ""
    while do_git != "Y" and do_git != "N":
        print("Do git add / git commit / git push ? (Y/N)")
        do_git = input()
    for p in projects:
        if do_git == "Y":
            p.git()
        if not p.deploy():
            print("FAILED DEPLOYING " + p.name + "!!!")
    print("ALL DEPLOYED SUCCESSFULLY!!!")


main()
