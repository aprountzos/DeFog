from prometheus_api_client import PrometheusConnect


GBTOBYTE = 1073741824


class Metrics:
    def __init__(self, prom_ip, namespace, period, deletion_period, total_cpu, total_ram):

        self.prometheus_url = "http://" + prom_ip + ":9090"

        self.prom = PrometheusConnect(
            url=self.prometheus_url, disable_ssl=True)
        self.period = period
        self.deletion_period = deletion_period

        self.namespace = namespace
        self.cluster_total_cpu = total_cpu
        self.cluster_total_ram = total_ram * GBTOBYTE

    def getRequestDataList(self):

        data = []
        request_query = "sum(increase(request_total{namespace=~\"" + self.namespace + \
            "\", deployment=~\".*\", dst_service!=\"\"}[" + self.period + \
            "])) by (dst_service, dst_target_service, dst_target_cluster, direction)"

        linkerd_g_request = "sum(increase(request_total{deployment=~\"linkerd-gateway\", dst_service!=\"\"}[" + \
            self.period + \
            "])) by (dst_service, dst_target_service, dst_target_cluster, direction)"

        requests = self.prom.custom_query(request_query)

        lin_requests = self.prom.custom_query(linkerd_g_request)

        requests = requests + lin_requests

        for item in requests:
            metric = item.get("metric")
            if metric is not None:
                dst_service = metric.get("dst_service").split("-")[0]
                dst_target_service = metric.get("dst_target_service")
                if dst_target_service is not None:
                    dst_target_service = metric.get(
                        "dst_target_service").split("-")[0]
                dst_target_cluster = metric.get("dst_target_cluster")
                req = int(float(item["value"][1]))
                tmp = {
                    'dst_service': dst_service,
                    'dst_target_service': dst_target_service,
                    'dst_target_cluster': dst_target_cluster,
                    'requests': req
                }
                data.append(tmp)

        return data

    def getMirroredLatency(self):

        ninety_five = {}

        ninety_five_query = "histogram_quantile(0.95, sum(rate(response_latency_ms_bucket{deployment=~\".*\", dst_target_cluster!=\"\", dst_namespace=~\"" + \
            self.namespace + "\"}[" + self.period + "])) by (le, dst_service))"

        ninety_five_response = self.prom.custom_query(ninety_five_query)

        for item in ninety_five_response:
            if item.get("value")[1] == "NaN":
                pass
                # ninety_five[item["metric"]["dst_service"]] = None
            else:
                ninety_five[item["metric"]["dst_service"]
                            ] = float(item["value"][1])

        return ninety_five

    def getInClusterLatency(self):

        ninety_five = {}

        ninety_five_query = "histogram_quantile(0.95, sum(rate(response_latency_ms_bucket{deployment=~\".*\", namespace=~\"" + \
            self.namespace + "\"}[" + self.period + "])) by (le, deployment))"
        ninety_five_response = self.prom.custom_query(ninety_five_query)

        for item in ninety_five_response:
            if item.get("value")[1] == "NaN":
                pass
                # ninety_five[item["metric"]["deployment"]] = None
            else:
                try:
                    ninety_five[item["metric"]["deployment"]
                                ] = float(item["value"][1])
                except:
                    pass

        return ninety_five

    def getResources(self, service):
        cpu_query = "sum(rate(container_cpu_usage_seconds_total{image!=\"\", namespace=\"" + \
            self.namespace + "\", pod=~\"" + service + ".*\" }[30s])) by (pod)"
        ram_query = "sum(container_memory_working_set_bytes{image!=\"\", namespace=\"" + \
            self.namespace + "\", pod=~\"" + service + ".*\" }) by (pod)"

        cpu_response = self.prom.custom_query(cpu_query)
        ram_response = self.prom.custom_query(ram_query)

        try:
            cpu = float(cpu_response[0].get("value")[1])
            ram = float(ram_response[0].get("value")[1])
        except IndexError as e:
            cpu = 0
            ram = 0
        # sum(container_cpu_usage_seconds_total{image!="", namespace="scheduled", pod=~"currency.*"}) by (pod)
        return cpu, ram

    def getMachineData(self):
        query = "sum(rate(container_cpu_usage_seconds_total{id=\"/\"}[" + self.period + "]))"
        metrics = self.prom.custom_query(query)
        cpu_usage = 0.0
        memory_usage_bytes = 0.0
        for item in metrics:
            cpu_usage = float(item["value"][1]) * 1000

        query = "sum(rate(container_cpu_usage_seconds_total{id=\"/\"}[" + self.period + "]))"
        metrics = self.prom.custom_query(query)
        cpu_percentage = 0.0
        memory_usage_bytes = 0.0
        for item in metrics:
            cpu_percentage = (
                float(item["value"][1]) / self.cluster_total_cpu) * 100

        query = "sum(container_memory_working_set_bytes{id=\"/\"})"
        metrics = self.prom.custom_query(query)
        for item in metrics:
            memory_usage_bytes = float(item["value"][1])

        memory_percentage = (memory_usage_bytes / self.cluster_total_ram) * 100

        return cpu_usage, memory_usage_bytes, cpu_percentage, memory_percentage
