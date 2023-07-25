from math import ceil
import os
import time
from Reader import getResources
from Utils import Utils
from Metrics import Metrics

NAMESPACE = os.environ["target_namespace"]
CPU_MAX = os.environ["cpu_max"]
RAM_MAX = os.environ["ram_max"]
TOTAL_RAM = os.environ["total_ram"]
TOTAL_CPU = os.environ["total_cpu"]
MODE = int(os.environ["mode"])
SPLIT_LIMIT = float(os.environ["split_limit"])

PERIOD = "30s"
YAMLPATH = "manifests/deployments"
IGNORE = ["frontend", "mongo-statefulset",
          "mysql", "apache", "keyrockservice", "keyrock"]

MIBTOBYTE = 1048576


class Scheduler:

    def __init__(self, period, deletion_period, namespace, total_ram, total_cpu, max_cpu_percentage, max_ram_percentage, deployment_path):
        self.period = period
        self.deletion_period = deletion_period
        self.namespace = namespace
        self.total_ram = total_ram
        self.total_cpu = total_cpu
        self.max_cpu_percentage = max_cpu_percentage
        self.max_ram_percentage = max_ram_percentage
        self.requests = dict()
        self.limits = dict()
        self.deployment_path = deployment_path
        self.utilsObj = None
        self.metricsObj = None
        self.ignore = IGNORE

    def InitData(self):
        self.utilsObj = Utils(self.namespace)
        prom_ip = self.utilsObj.getPrometheus()
        self.metricsObj = Metrics(prom_ip, self.namespace, self.period,
                                  self.deletion_period, self.total_cpu, self.total_ram)
        # self.metricsObj.initMachineData()
        self.requests, self.limits = getResources(self.deployment_path)

    def classifyRequestSort(self):
        admitted = []
        mirrored = []
        deployed = self.utilsObj.getDeploy()
        requestData = self.metricsObj.getRequestDataList()

        for request in requestData:
            if request["dst_target_cluster"]:
                if request["dst_target_service"] not in deployed:
                    mirrored.append(request)
            else:
                if request["dst_service"] in deployed:
                    admitted.append(request)

        sortedAdmitted = sorted(
            admitted, key=lambda a: a["requests"], reverse=False)
        sortedMirrored = sorted(
            mirrored, key=lambda a: a["requests"], reverse=True)

        return sortedAdmitted, sortedMirrored

    def classifyLatencySort(self):
        admitted = self.metricsObj.getInClusterLatency()
        mirrored = self.metricsObj.getMirroredLatency()
        admitted = dict(sorted(admitted.items(), key=lambda item: (
            item[1] is None, item[1]), reverse=True))

        mirrored = dict(
            sorted(mirrored.items(), key=lambda item: (item[1] is None, item[1])))
        for key in self.ignore:
            admitted.pop(key, None)
        print("admitted:\n", admitted)
        print("mirrorred:\n", mirrored)
        return admitted, mirrored

    def lfuDeploy(self):
        deployed = self.utilsObj.getDeploy()
        admitted, mirrored = self.classifyRequestSort()
        check = deployed + self.ignore
        recently_deployed = []

        while mirrored:
            service = mirrored[0]
            service_name = service["dst_target_service"].split("-")[0]
            print(f"** {service_name} scheduled for deployment. **")
            if service_name in check:
                print(
                    f"** {service_name} already deployed or must be ignored. **")
                mirrored.pop(0)
            elif self.availabeResources(service_name) and service_name not in recently_deployed:
                recently_deployed.append(service_name)
                self.utilsObj.deploy(self.deployment_path, service_name)
                print(f"** {service_name} deployed. **")
                mirrored.pop(0)
            else:
                print(
                    f"** Not available resources, {service_name} cannot be deployed. **")
                if admitted:
                    admitted_service = admitted[0]
                    admitted_name = admitted_service["dst_service"].split(
                        "-")[0]
                    print(f"** {admitted_name} scheduled for deletion. **")
                    if admitted_service["requests"] < service["requests"] and admitted_name not in recently_deployed:
                        self.utilsObj.deleteDeploy(admitted_name)
                        print(f"** {admitted_name} deleted. **")
                        admitted.pop(0)
                    else:
                        print(
                            f"** {admitted_name} should not be deleted. **")
                        mirrored.pop(0)
                        # break
                else:
                    print(
                        "** No service deployed. **")
                    mirrored.pop(0)
                    # break

    def lfuRamFitDeploy(self):
        deployed = self.utilsObj.getDeploy()
        admitted, mirrored = self.classifyRequestSort()
        check = deployed + self.ignore
        recently_deployed = []

        while mirrored:
            service = mirrored[0]
            service_name = service["dst_target_service"].split("-")[0]
            print(f"** {service_name} scheduled for deployment. **")
            if service_name in check:
                print(
                    f"** {service_name} already deployed or must be ignored. **")
                mirrored.pop(0)
            elif self.availabeResources(service_name) and service_name not in recently_deployed:
                recently_deployed.append(service_name)
                self.utilsObj.deploy(self.deployment_path, service_name)
                print(f"** {service_name} deployed. **")
                mirrored.pop(0)
            else:
                print(
                    f"** Not available resources, {service_name} cannot be deployed. **")
                if admitted:
                    ram_sorted_admitted = {}
                    for admitted_service in admitted:
                        admitted_name = admitted_service["dst_service"].split(
                            "-")[0]
                        if admitted_name not in self.ignore:
                            cpu, ram = self.metricsObj.getResources(
                                admitted_name)
                            ram_sorted_admitted[admitted_name] = ram
                    ram_sorted_admitted = dict(sorted(ram_sorted_admitted.items(
                    ), key=lambda item: (item[1] is None, item[1]), reverse=True))
                    service_ram = self.requests[service_name]["memory"] * MIBTOBYTE
                    try:
                        delete = next(iter((ram_sorted_admitted.items())))
                        admitted_name = delete[0]
                        admitted_ram = delete[1]
                        print(f"** {admitted_name} scheduled for deletion. **")
                        if service_ram < admitted_ram and admitted_name not in recently_deployed:
                            self.utilsObj.deleteDeploy(admitted_name)
                            print(f"** {admitted_name} deleted. **")
                            admitted.pop(0)
                        else:
                            print(
                                f"** {admitted_name} should not be deleted. **")
                            mirrored.pop(0)
                            # break
                    except:
                        print("** No service deployed. **")
                        mirrored.pop(0)
                        # break
                else:
                    print(
                        "** No service deployed. **")
                    mirrored.pop(0)
                    # break

    def latencyDeploy(self):
        deployed = self.utilsObj.getDeploy()
        deployed_services, mirrored_services = self.classifyLatencySort()

        temp = []
        temp = temp + self.ignore
        while mirrored_services:
            # self.updateSplits()
            service = next(iter((mirrored_services.items())))
            service_name = service[0].split("-")[0]
            print(f"** {service_name} scheduled for deployment. **")
            if service_name in deployed + self.ignore:
                print(
                    f"** {service_name} already deployed or must be ignored. **")
                mirrored_services.pop(list(mirrored_services.keys())[0])
                temp.append(service_name)
            elif self.availabeResources(service_name) and service_name not in temp:
                mirrored_services.pop(list(mirrored_services.keys())[0])
                temp.append(service_name)

                self.utilsObj.deploy(self.deployment_path, service_name)
                print(f"** {service_name} deployed. **")
                # self.utilsObj.disableMirror(service_name)
                # time.sleep(2)
            else:
                print(
                    f"** Not available resources, {service_name} cannot be deployed. **")
                if deployed_services:
                    # print("SERVICE I WANT TO DEPLOY: ", service_name)
                    delete = next(iter((deployed_services.items())))
                    delete_name = delete[0].split("-")[0]
                    print(f"** {delete_name} scheduled for deletion. **")
                    if delete[1] > service[1] and delete_name not in temp and delete_name in deployed:
                        deployed_services.pop(
                            list(deployed_services.keys())[0])

                        # self.utilsObj.enableMirror(delete_name)
                        self.utilsObj.deleteDeploy(delete_name)
                        print(f"** {delete_name} deleted. **")
                        # time.sleep(2)
                    else:
                        print(
                            f"** {delete_name} should not be deleted. **")
                        mirrored_services.pop(
                            list(mirrored_services.keys())[0])
                        # break
                else:
                    print(
                        "** No service deployed. **")
                    mirrored_services.pop(list(mirrored_services.keys())[0])
                    # break

    def latencyRamFitDeploy(self):
        deployed = self.utilsObj.getDeploy()
        deployed_services, mirrored_services = self.classifyLatencySort()

        temp = []
        temp = temp + self.ignore

        while mirrored_services:
            # self.updateSplits()
            service = next(iter((mirrored_services.items())))
            service_name = service[0].split("-")[0]
            print(f"** {service_name} scheduled for deployment. **")
            if service_name in deployed + self.ignore:
                print(
                    f"** {service_name} already deployed or must be ignored. **")
                mirrored_services.pop(list(mirrored_services.keys())[0])
                temp.append(service_name)
            elif self.availabeResources(service_name) and service_name not in temp:
                mirrored_services.pop(list(mirrored_services.keys())[0])
                temp.append(service_name)
                print("Deploying: " + service_name)
                self.utilsObj.deploy(self.deployment_path, service_name)
                print(f"** {service_name} deployed. **")
            else:
                if deployed_services:
                    sorted_deploys = {}
                    for deploy in deployed_services:
                        if deploy not in self.ignore:
                            _, ram = self.metricsObj.getResources(deploy)
                            sorted_deploys[deploy] = ram
                    sorted_deploys = dict(sorted(sorted_deploys.items(), key=lambda item: (
                        item[1] is None, item[1]), reverse=True))
                    # print(sorted_deploys)
                    to_deploy_ram = self.requests[service_name]["memory"] * MIBTOBYTE

                    try:
                        delete = next(iter((sorted_deploys.items())))
                    except:
                        break
                    delete_name = delete[0]
                    print(f"** {delete_name} scheduled for deletion. **")
                    # print(delete_name)
                    # print(to_deploy_ram)
                    if to_deploy_ram < delete[1] and delete_name not in temp:
                        print("DELETING: ", delete_name)
                        # self.utilsObj.enableMirror(delete_name)
                        self.utilsObj.deleteDeploy(delete_name)
                        print(f"** {delete_name} deleted. **")
                        # time.sleep(2)
                    else:
                        print(
                            f"** {delete_name} should not be deleted. **")
                        # mirrored_services.pop(
                        #     list(mirrored_services.keys())[0])
                        break
                else:
                    print(
                        "** No service deployed. **")
                    # mirrored_services.pop(list(mirrored_services.keys())[0])
                    break

    def updateSplits(self):
        requests, limits = getResources(self.deployment_path)
        services, _ = self.utilsObj.getServices()
        ts = self.utilsObj.getTrafficSplits()
        deploys = self.utilsObj.getDeploy()
        for svc in services:
            if svc not in deploys:
                if not self.utilsObj.checkSplit(svc):
                    self.utilsObj.splitService(svc, 100)
            else:
                weight = self.calculateWeight(svc)
                self.utilsObj.splitService(svc, weight)

    def calculateWeight(self, svc):
        current_cpu, current_ram = self.metricsObj.getResources(svc)
        if current_cpu == 0 and current_ram == 0:
            return 0

        current_cpua = current_cpu * 1000

        desired_cpu = self.limits[svc]["cpu"]
        desired_ram = self.limits[svc]["memory"] * MIBTOBYTE

        if desired_cpu == 0 and desired_ram == 0:
            return 0
        cpu = (current_cpua / (desired_cpu * SPLIT_LIMIT))
        ram = (current_ram / (desired_ram * SPLIT_LIMIT))
        weight = (cpu + ram)
        if weight > 1:
            weight -= 1
            weight *= 100
            weight = ceil(weight)
        else:
            weight = 0

        return weight

    def availabeResources(self, deploy):
        max_cpu = self.metricsObj.cluster_total_cpu * \
            1000 * self.max_cpu_percentage / 100
        max_ram = self.metricsObj.cluster_total_ram * self.max_ram_percentage / 100
        current_cpu, current_ram, _, _ = self.metricsObj.getMachineData()
        cpu2 = 0
        ram2 = 0
        if "proxy" in deploy:
            tmp = deploy.split("proxy")
            name = "".join(tmp)
            cpu2 = self.requests[name]["cpu"]
            ram2 = self.requests[name]["memory"]

        cpu_request = self.requests[deploy]["cpu"] + cpu2
        ram_request = (self.requests[deploy]["memory"]
                       * MIBTOBYTE) + (ram2 * MIBTOBYTE)

        print("TOTAL CPU: ", self.metricsObj.cluster_total_cpu *
              1000, ", MAX CPU: ", max_cpu)
        print("TOTAL RAM: ", self.metricsObj.cluster_total_ram,
              ", MAX RAM: ", max_ram)
        print("CURRENT CPU: ", current_cpu)
        print("CURRENT RAM: ", current_ram)
        print("AFTER DEPLOYING: ", deploy)

        current_cpu += cpu_request
        current_ram += ram_request

        print("AFTER DEPLOYMENT CPU: ", current_cpu)
        print("AFTER DEPLOYMENT RAM: ", current_ram)

        if current_cpu <= max_cpu and current_ram <= max_ram:
            return True
        else:
            return False

    def schedulerLoop(self, mode=4):
        while True:

            self.requests, self.limits = getResources(self.deployment_path)
            timeout = time.time() + 30
            paused = True
            while paused:
                print("Managing Splits\n")
                self.updateSplits()
                time.sleep(10)
                if time.time() > timeout:
                    paused = False

            print("Scheduling apps")
            if mode == 0:
                self.lfuDeploy()
            elif mode == 1:
                self.lfuRamFitDeploy()
            elif mode == 2:
                self.latencyDeploy()
            elif mode == 3:
                self.latencyRamFitDeploy()
            elif mode == 4:
                continue


def main():
    sc = Scheduler(PERIOD, PERIOD, NAMESPACE, float(TOTAL_RAM), int(
        TOTAL_CPU), int(CPU_MAX), int(RAM_MAX), YAMLPATH)
    sc.InitData()
    sc.schedulerLoop(mode=MODE)


if __name__ == '__main__':
    main()
