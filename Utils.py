import os
import time
import yaml

from kubernetes import config
from kubernetes import client
from kubernetes.client.rest import ApiException
from Reader import readYaml


CONTEXT = 'k3d-edge1'


class Utils:
    def __init__(self, namespace):
        try:
            config.load_incluster_config()
        except config.ConfigException:
            try:
                config.load_kube_config(context=CONTEXT)
            except config.ConfigException:
                raise Exception("Could not configure kubernetes python client")

        self.namespace = namespace

    def getServices(self, ignore=["frontend", "frontendexternal", "apacheservice"]):
        # deploys = self.getDeploy()
        services = []
        mirrored_services = []
        kubectl = client.CoreV1Api()

        try:
            response = kubectl.list_namespaced_service(
                namespace=self.namespace, watch=False)
        except ApiException as e:
            print(e)

        for i in response.items:
            service = i.metadata.name
            if service not in ignore:
                try:
                    cluster = i.metadata.labels["mirror.linkerd.io/cluster-name"]
                    mirrored_services.append(service)
                except:
                    services.append(service)

        return services, mirrored_services

    def getDeploy(self, ignore=["frontend", "apache"]):
        kubectl = client.AppsV1Api()
        deployments = []
        try:
            response = kubectl.list_namespaced_deployment(self.namespace)
        except ApiException as e:
            print(e)
            print("get deploy it brakes")

        try:
            for i in response.items:
                deploy = i.metadata.name
                if deploy not in ignore:
                    deployments.append(deploy)
        except TypeError as e:
            print(e)
        return deployments

    def getTrafficSplits(self):
        kubectl = client.CustomObjectsApi()
        group = "split.smi-spec.io"
        version = "v1alpha2"
        plural = "trafficsplits"
        traffic_splits = {}
        try:
            response = kubectl.list_namespaced_custom_object(
                group, version, self.namespace, plural)
        except ApiException as e:
            print(e)

        for ts in response["items"]:
            split = ts["metadata"]["name"]
            spec = ts["spec"]
            traffic_splits[split] = spec
        return traffic_splits

    def getTrafficSplit(self, svc):
        kubectl = client.CustomObjectsApi()
        group = "split.smi-spec.io"
        version = "v1alpha2"
        plural = "trafficsplits"
        trafficSplit = None
        backends = []
        try:
            trafficSplit = kubectl.get_namespaced_custom_object(
                group, version, self.namespace, plural, svc+"-ts")
        except ApiException as e:
            # print(e)
            pass
        if trafficSplit != None:
            for backend in trafficSplit["spec"]["backends"]:
                backends.append(backend["service"])
        else:
            backends = None
        return backends

    def split(self, svc, mirrored):
        ts = self.getTrafficSplits()
        kubectl = client.CustomObjectsApi()
        group = "split.smi-spec.io"
        version = "v1alpha2"
        plural = "trafficsplits"
        values = []
        spec = {}
        values.append({"service": svc, "weight": 0})
        values.append({"service": mirrored, "weight": 1})
        spec["service"] = svc
        spec["backends"] = values

        file = "components/ts_split.yaml"
        if os.path.isfile(file):
            with open(file, 'r') as stream:
                body = yaml.safe_load(stream)

        body["metadata"]["namespace"] = self.namespace
        body["metadata"]["name"] = svc + "-ts"
        body["spec"] = spec

        try:
            if svc + "-ts" in ts.keys():
                kubectl.delete_namespaced_custom_object(
                    group, version, self.namespace, plural, svc + "-ts")
            kubectl.create_namespaced_custom_object(
                group, version, self.namespace, plural, body)
        except ApiException as e:
            print(e)

    def splitMultiple(self, svc, mirrored, weight):
        ts = self.getTrafficSplits()
        kubectl = client.CustomObjectsApi()
        group = "split.smi-spec.io"
        version = "v1alpha2"
        plural = "trafficsplits"
        values = []
        spec = {}
        values.append({"service": svc, "weight": (100 - weight)})
        if len(mirrored) != 0:
            weight = (1 / len(mirrored)) * weight
            for m in mirrored:
                values.append({"service": m, "weight": weight})

        spec["service"] = svc
        spec["backends"] = values

        file = "components/ts_split.yaml"
        if os.path.isfile(file):
            with open(file, 'r') as stream:
                body = yaml.safe_load(stream)

        body["metadata"]["namespace"] = self.namespace
        body["metadata"]["name"] = svc + "-ts"
        body["spec"] = spec

        try:
            if svc + "-ts" in ts.keys():
                kubectl.delete_namespaced_custom_object(
                    group, version, self.namespace, plural, svc + "-ts")
            kubectl.create_namespaced_custom_object(
                group, version, self.namespace, plural, body)
        except ApiException as e:
            print(e)

    def checkSplit(self, svc):

        ts = self.getTrafficSplit(svc)
        # print(ts)
        alive = False
        if ts is not None:
            for service in ts:
                alive = self.checkEndpoint(service)
                if not alive:
                    print(service + " has no endpoint")
                    break
        return alive

    def deploy(self, dep_path, name):
        names = []
        kubectl = client.AppsV1Api()
        if "proxy" in name:
            tmp = name.split("proxy")
            name = "".join(tmp)
        body = readYaml(dep_path, name)
        try:
            for item in readYaml(dep_path, name)[0]:
                api_response = kubectl.create_namespaced_deployment(
                    self.namespace, item)
                names.append(item["metadata"]["name"])
        except ApiException as e:
            print(e)
            print("breaks in deploy")
        for name in names:
            self.wait_for_deployment_complete(name)
            self.splitService(name, 0)

    def wait_for_deployment_complete(self, deployment_name):
        kubectl = client.AppsV1Api()
        stat = False

        while True:
            time.sleep(2)

            try:
                response = kubectl.read_namespaced_deployment_status(
                    deployment_name, self.namespace)
                status = response.status
                spec = response.spec
                meta = response.metadata
                stat = (status.updated_replicas == spec.replicas and status.replicas == spec.replicas
                        and status.available_replicas == spec.replicas and status.observed_generation >= meta.generation)
            except ApiException as e:
                print(e)

            if stat:
                return

    def deleteDeploy(self, name):
        self.splitService(name, 100)
        kubectl = client.AppsV1Api()
        try:
            response = kubectl.delete_namespaced_deployment(
                name, self.namespace)
            self.wait_for_deployment_deletion(name)

        except ApiException as e:
            print(e)
        try:
            response = kubectl.delete_namespaced_deployment(
                name+"proxy", self.namespace)
            self.wait_for_deployment_deletion(name+"proxy")
        except ApiException as e:
            print(e)

        try:
            response = kubectl.delete_namespaced_deployment(
                name.strip("proxy"), self.namespace)
            self.wait_for_deployment_deletion(name+"proxy")
        except ApiException as e:
            print(e)

    def wait_for_deployment_deletion(self, deployment_name):
        kubectl = client.AppsV1Api()

        while True:
            deploys = []
            time.sleep(2)

            try:
                deployments = kubectl.list_namespaced_deployment(
                    self.namespace)
                for i in deployments.items:
                    deploys.append(i.metadata.name)
                if deployment_name not in deploys:
                    return
                else:
                    print("Waiting for delete...")

            except ApiException as e:
                print(e)

    def splitService(self, svc, weight):
        kubectl = client.CoreV1Api()
        _, mirrored = self.getServices()
        ts = self.getTrafficSplits()
        services = []
        for name in mirrored:
            try:
                service = kubectl.read_namespaced_service(name, self.namespace)
                orig_svc = service.metadata.annotations["mirror.linkerd.io/remote-svc-fq-name"].split(
                    ".").pop(0)
                alive = self.checkEndpoint(name)
                if orig_svc == svc and alive:
                    services.append(name)

            except ApiException as e:
                print(e)
        try:
            self.splitMultiple(svc, services, weight)

        except IndexError as e:
            print(e)

    def checkEndpoint(self, svc):
        kubectl = client.CoreV1Api()
        response = None
        try:
            response = kubectl.read_namespaced_endpoints(svc, self.namespace)
        except ApiException as e:
            print(e)
        if response is None:
            return False
        if response.subsets is None:
            return False
        else:
            return True

    def updateSplits(self):
        services, _ = self.getServices()
        ts = self.getTrafficSplits()
        deploys = self.getDeploy()
        for svc in services:
            if svc not in deploys:
                if not self.checkSplit(svc):
                    self.splitService(svc, 1)

    def getPrometheus(self):

        kubectl = client.CoreV1Api()
        try:
            response = kubectl.read_namespaced_endpoints(
                "prometheus", "linkerd-viz")
        except ApiException as e:
            print(e)
        return response.subsets[0].addresses[0].ip
