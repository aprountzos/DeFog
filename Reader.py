import yaml
import os
import re


def readYaml(path, file):
    file = file + ".yaml"
    file = os.path.join(path, file)
    body = []

    if os.path.isfile(file):
        with open(file, 'r') as stream:
            body.append(list(yaml.load_all(stream, Loader=yaml.FullLoader)))

    return body


def readMulYaml(path):
    loaded_data = []
    for filename in os.listdir(path):
        _, extension = os.path.splitext(filename)
        # print(filename, extension)
        if extension == ".yaml" or extension == ".yml":
            # print(filename, extension)
            file = os.path.join(path, filename)
            if os.path.isfile(file):
                with open(file, 'r') as stream:
                    loaded_data.append(
                        list(yaml.load_all(stream, Loader=yaml.FullLoader)))
    return loaded_data


def getResources(path):
    requests = {}
    limits = {}
    data = readMulYaml(path)
    for docs in data:
        for doc in docs:
            if doc["kind"] == "Deployment":
                name = doc["metadata"]["name"]
                try:
                    temp = doc["spec"]["template"]["spec"]["containers"][0]["resources"]
                    requests[name] = temp["requests"]
                    limits[name] = temp["limits"]
                except:
                    requests[name] = {'cpu': "0", 'memory': "0"}
                    limits[name] = {'cpu': "0", 'memory': "0"}

    for data, values in requests.items():

        for k, v in values.items():
            tmp = re.findall('[0-9]+', v)[0]
            values[k] = int(tmp)

    for data, values in limits.items():

        for k, v in values.items():
            tmp = re.findall('[0-9]+', v)[0]
            values[k] = int(tmp)

    return requests, limits
