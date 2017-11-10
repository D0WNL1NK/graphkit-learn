import networkx as nx


def loadCT(filename):
    content = open(filename).read().splitlines()
    G = nx.Graph(name=str(content[0]))
    tmp = content[1].split(" ")
    if tmp[0] == '':
        nb_nodes = int(tmp[1])
        nb_edges = int(tmp[2])
    else:
        nb_nodes = int(tmp[0])
        nb_edges = int(tmp[1])

    for i in range(0, nb_nodes):
        tmp = content[i + 2].split(" ")
        tmp = [x for x in tmp if x != '']
        G.add_node(i, label=tmp[3])

    for i in range(0, nb_edges):
        tmp = content[i+G.number_of_nodes()+2].split(" ")
        tmp = [x for x in tmp if x != '']
        G.add_edge(int(tmp[0]) - 1, int(tmp[1]) - 1, label=int(tmp[3]))
    return G


def loadGXL(filename):
    import networkx as nx
    import xml.etree.ElementTree as ET

    tree = ET.parse(filename)
    root = tree.getroot()
    index = 0
    G = nx.Graph()
    dic={}
    for node in root.iter('node'):
        label = node.find('attr')[0].text
        dic[node.attrib['id']] = index
        G.add_node(index, id=node.attrib['id'], label=label)
        index += 1
        
    for edge in root.iter('edge'):
        label = edge.find('attr')[0].text
        G.add_edge(dic[edge.attrib['from']], dic[edge.attrib['to']], label=label)
    return G


def loadDataset(filename):
    from os.path import dirname, splitext

    dirname_dataset = dirname(filename)
    extension = splitext(filename)[1][1:]
    data = []
    y = []
    if(extension == "ds"):
        content = open(filename).read().splitlines()
        for i in range(0, len(content)):
            tmp = content[i].split(' ')
            data.append(loadCT(dirname_dataset + '/' + tmp[0]))
            y.append(float(tmp[1]))
    elif(extension == "cxl"):
        import xml.etree.ElementTree as ET

        tree = ET.parse(filename)
        root = tree.getroot()
        data = []
        y = []
        for graph in root.iter('print'):
            mol_filename = graph.attrib['file']
            mol_class = graph.attrib['class']
            data.append(loadGXL(dirname_dataset + '/' + mol_filename))
            y.append(mol_class)

    return data, y
