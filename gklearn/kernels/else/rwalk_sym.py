#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Dec 23 16:53:57 2018

@author: ljia
@references: S Vichy N Vishwanathan, Nicol N Schraudolph, Risi Kondor, and 
Karsten M Borgwardt. Graph kernels. Journal of Machine Learning Research, 
11(Apr):1201–1242, 2010.
"""

import sys
sys.path.insert(0, "../")
import time
from functools import partial
from tqdm import tqdm

import networkx as nx
import numpy as np
from scipy.sparse import identity, kron
from scipy.sparse.linalg import cg
from scipy.optimize import fixed_point

from gklearn.utils.graphdataset import get_dataset_attributes
from gklearn.utils.parallel import parallel_gm

def randomwalkkernel(*args,
                     # params for all method.
                     compute_method=None,
                     weight=1, 
                     p=None, 
                     q=None,
                     edge_weight=None,
                     # params for conjugate and fp method.
                     node_kernels=None, 
                     edge_kernels=None,
                     node_label='atom',
                     edge_label='bond_type',
                     # params for spectral method.
                     sub_kernel=None,                                          
                     n_jobs=None):
    """Calculate random walk graph kernels.
    Parameters
    ----------
    Gn : List of NetworkX graph
        List of graphs between which the kernels are calculated.
    /
    G1, G2 : NetworkX graphs
        2 graphs between which the kernel is calculated.
    node_label : string
        node attribute used as label. The default node label is atom.
    edge_label : string
        edge attribute used as label. The default edge label is bond_type.
    h : integer
        Longest length of walks.
    method : string
        Method used to compute the random walk kernel. Available methods are 'sylvester', 'conjugate', 'fp', 'spectral' and 'kron'.

    Return
    ------
    Kmatrix : Numpy matrix
        Kernel matrix, each element of which is the path kernel up to d between 2 praphs.
    """
    compute_method = compute_method.lower()
    Gn = args[0] if len(args) == 1 else [args[0], args[1]]

    eweight = None
    if edge_weight == None:
        print('\n None edge weight specified. Set all weight to 1.\n')
    else:
        try:
            some_weight = list(
                nx.get_edge_attributes(Gn[0], edge_weight).values())[0]
            if isinstance(some_weight, float) or isinstance(some_weight, int):
                eweight = edge_weight
            else:
                print(
                    '\n Edge weight with name %s is not float or integer. Set all weight to 1.\n'
                    % edge_weight)
        except:
            print(
                '\n Edge weight with name "%s" is not found in the edge attributes. Set all weight to 1.\n'
                % edge_weight)

    ds_attrs = get_dataset_attributes(
        Gn,
        attr_names=['node_labeled', 'node_attr_dim', 'edge_labeled',
                    'edge_attr_dim', 'is_directed'],
        node_label=node_label,
        edge_label=edge_label)
    ds_attrs['node_attr_dim'] = 0
    ds_attrs['edge_attr_dim'] = 0
    
    # remove graphs with no edges, as no walk can be found in their structures, 
    # so the weight matrix between such a graph and itself might be zero.
    len_gn = len(Gn)
    Gn = [(idx, G) for idx, G in enumerate(Gn) if nx.number_of_edges(G) != 0]
    idx = [G[0] for G in Gn]
    Gn = [G[1] for G in Gn]
    if len(Gn) != len_gn:
        print('\n %d graphs are removed as they don\'t contain edges.\n' %
              (len_gn - len(Gn)))

    start_time = time.time()
    
#    # get vertex and edge concatenated labels for each graph
#    label_list, d = getLabels(Gn, node_label, edge_label, ds_attrs['is_directed'])
#    gmf = filterGramMatrix(A_wave_list[0], label_list[0], ('C', '0', 'O'), ds_attrs['is_directed'])

    if compute_method == 'sylvester':
        import warnings
        warnings.warn('All labels are ignored.')
        Kmatrix = _sylvester_equation(Gn, weight, p, q, eweight, n_jobs)

    elif compute_method == 'conjugate':
        Kmatrix = _conjugate_gradient(Gn, weight, p, q, ds_attrs, 
                                              node_kernels, edge_kernels, 
                                              node_label, edge_label, eweight, n_jobs)
        
    elif compute_method == 'fp':
        Kmatrix = _fixed_point(Gn, weight, p, q, ds_attrs, node_kernels, 
                                       edge_kernels, node_label, edge_label, 
                                       eweight, n_jobs)

    elif compute_method == 'spectral':
        import warnings
        warnings.warn('All labels are ignored. Only works for undirected graphs.')
        Kmatrix = _spectral_decomposition(Gn, weight, p, q, sub_kernel, eweight, n_jobs)

    elif compute_method == 'kron':
        for i in range(0, len(Gn)):
            for j in range(i, len(Gn)):
                Kmatrix[i][j] = _randomwalkkernel_kron(Gn[i], Gn[j],
                                                       node_label, edge_label)
                Kmatrix[j][i] = Kmatrix[i][j]
    else:
        raise Exception(
            'compute method name incorrect. Available methods: "sylvester", "conjugate", "fp", "spectral" and "kron".'
        )

    run_time = time.time() - start_time
    print(
        "\n --- kernel matrix of random walk kernel of size %d built in %s seconds ---"
        % (len(Gn), run_time))

    return Kmatrix, run_time, idx


###############################################################################
def _sylvester_equation(Gn, lmda, p, q, eweight, n_jobs):
    """Calculate walk graph kernels up to n between 2 graphs using Sylvester method.

    Parameters
    ----------
    G1, G2 : NetworkX graph
        Graphs between which the kernel is calculated.
    node_label : string
        node attribute used as label.
    edge_label : string
        edge attribute used as label.

    Return
    ------
    kernel : float
        Kernel between 2 graphs.
    """
    Kmatrix = np.zeros((len(Gn), len(Gn)))

    if q == None:
        # don't normalize adjacency matrices if q is a uniform vector. Note
        # A_wave_list accually contains the transposes of the adjacency matrices.
        A_wave_list = [
            nx.adjacency_matrix(G, eweight).todense().transpose() for G in tqdm(
                Gn, desc='compute adjacency matrices', file=sys.stdout)
        ]
#        # normalized adjacency matrices
#        A_wave_list = []
#        for G in tqdm(Gn, desc='compute adjacency matrices', file=sys.stdout):
#            A_tilde = nx.adjacency_matrix(G, eweight).todense().transpose()   
#            norm = A_tilde.sum(axis=0)
#            norm[norm == 0] = 1
#            A_wave_list.append(A_tilde / norm)
        if p == None: # p is uniform distribution as default.
            def init_worker(Awl_toshare):
                global G_Awl
                G_Awl = Awl_toshare
            do_partial = partial(wrapper_se_do, lmda)   
            parallel_gm(do_partial, Kmatrix, Gn, init_worker=init_worker, 
                        glbv=(A_wave_list,), n_jobs=n_jobs)
            
#            pbar = tqdm(
#                total=(1 + len(Gn)) * len(Gn) / 2,
#                desc='calculating kernels',
#                file=sys.stdout)
#            for i in range(0, len(Gn)):
#                for j in range(i, len(Gn)):
#                    S = lmda * A_wave_list[j]
#                    T_t = A_wave_list[i]
#                    # use uniform distribution if there is no prior knowledge.
#                    nb_pd = len(A_wave_list[i]) * len(A_wave_list[j])
#                    p_times_uni = 1 / nb_pd
#                    M0 = np.full((len(A_wave_list[j]), len(A_wave_list[i])), p_times_uni)
#                    X = dlyap(S, T_t, M0)
#                    X = np.reshape(X, (-1, 1), order='F')
#                    # use uniform distribution if there is no prior knowledge.
#                    q_times = np.full((1, nb_pd), p_times_uni)
#                    Kmatrix[i][j] = np.dot(q_times, X)
#                    Kmatrix[j][i] = Kmatrix[i][j]
#                    pbar.update(1)

    return Kmatrix


def wrapper_se_do(lmda, itr):
    i = itr[0]
    j = itr[1]
    return i, j, _se_do(G_Awl[i], G_Awl[j], lmda)


def _se_do(A_wave1, A_wave2, lmda):
    from control import dlyap
    S = lmda * A_wave2
    T_t = A_wave1
    # use uniform distribution if there is no prior knowledge.
    nb_pd = len(A_wave1) * len(A_wave2)
    p_times_uni = 1 / nb_pd
    M0 = np.full((len(A_wave2), len(A_wave1)), p_times_uni)
    X = dlyap(S, T_t, M0)
    X = np.reshape(X, (-1, 1), order='F')
    # use uniform distribution if there is no prior knowledge.
    q_times = np.full((1, nb_pd), p_times_uni)
    return np.dot(q_times, X)


###############################################################################
def _conjugate_gradient(Gn, lmda, p, q, ds_attrs, node_kernels, edge_kernels, 
                        node_label, edge_label, eweight, n_jobs):
    """Calculate walk graph kernels up to n between 2 graphs using conjugate method.

    Parameters
    ----------
    G1, G2 : NetworkX graph
        Graphs between which the kernel is calculated.
    node_label : string
        node attribute used as label.
    edge_label : string
        edge attribute used as label.

    Return
    ------
    kernel : float
        Kernel between 2 graphs.
    """
    Kmatrix = np.zeros((len(Gn), len(Gn)))
    
#    if not ds_attrs['node_labeled'] and ds_attrs['node_attr_dim'] < 1 and \
#        not ds_attrs['edge_labeled'] and ds_attrs['edge_attr_dim'] < 1:
#        # this is faster from unlabeled graphs. @todo: why?
#        if q == None:
#            # don't normalize adjacency matrices if q is a uniform vector. Note
#            # A_wave_list accually contains the transposes of the adjacency matrices.
#            A_wave_list = [
#                nx.adjacency_matrix(G, eweight).todense().transpose() for G in 
#                    tqdm(Gn, desc='compute adjacency matrices', file=sys.stdout)
#            ]
#            if p == None: # p is uniform distribution as default.
#                def init_worker(Awl_toshare):
#                    global G_Awl
#                    G_Awl = Awl_toshare
#                do_partial = partial(wrapper_cg_unlabled_do, lmda)   
#                parallel_gm(do_partial, Kmatrix, Gn, init_worker=init_worker, 
#                            glbv=(A_wave_list,), n_jobs=n_jobs)
#    else:  
    # reindex nodes using consecutive integers for convenience of kernel calculation.
    Gn = [nx.convert_node_labels_to_integers(
            g, first_label=0, label_attribute='label_orignal') for g in tqdm(
                Gn, desc='reindex vertices', file=sys.stdout)]
    
    if p == None and q == None: # p and q are uniform distributions as default.
        def init_worker(gn_toshare):
            global G_gn
            G_gn = gn_toshare
        do_partial = partial(wrapper_cg_labled_do, ds_attrs, node_kernels, 
                             node_label, edge_kernels, edge_label, lmda)   
        parallel_gm(do_partial, Kmatrix, Gn, init_worker=init_worker, 
                    glbv=(Gn,), n_jobs=n_jobs)  
            
#            pbar = tqdm(
#                total=(1 + len(Gn)) * len(Gn) / 2,
#                desc='calculating kernels',
#                file=sys.stdout)
#            for i in range(0, len(Gn)):
#                for j in range(i, len(Gn)):
#                    result = _cg_labled_do(Gn[i], Gn[j], ds_attrs, node_kernels,
#                                           node_label, edge_kernels, edge_label, lmda)
#                    Kmatrix[i][j] = result
#                    Kmatrix[j][i] = Kmatrix[i][j]
#                    pbar.update(1)
    return Kmatrix


def wrapper_cg_unlabled_do(lmda, itr):
    i = itr[0]
    j = itr[1]
    return i, j, _cg_unlabled_do(G_Awl[i], G_Awl[j], lmda)


def _cg_unlabled_do(A_wave1, A_wave2, lmda):
    nb_pd = len(A_wave1) * len(A_wave2)
    p_times_uni = 1 / nb_pd
    w_times = kron(A_wave1, A_wave2).todense()
    A = identity(w_times.shape[0]) - w_times * lmda
    b = np.full((nb_pd, 1), p_times_uni)
    x, _ = cg(A, b)
    # use uniform distribution if there is no prior knowledge.
    q_times = np.full((1, nb_pd), p_times_uni)
    return np.dot(q_times, x)


def wrapper_cg_labled_do(ds_attrs, node_kernels, node_label, edge_kernels, 
                         edge_label, lmda, itr):
    i = itr[0]
    j = itr[1]
    return i, j, _cg_labled_do(G_gn[i], G_gn[j], ds_attrs, node_kernels, 
                               node_label, edge_kernels, edge_label, lmda)


def _cg_labled_do(g1, g2, ds_attrs, node_kernels, node_label, 
                  edge_kernels, edge_label, lmda):
    # Frist, ompute kernels between all pairs of nodes, method borrowed
    # from FCSP. It is faster than directly computing all edge kernels 
    # when $d_1d_2>2$, where $d_1$ and $d_2$ are vertex degrees of the
    # graphs compared, which is the most case we went though. For very 
    # sparse graphs, this would be slow.
    vk_dict = computeVK(g1, g2, ds_attrs, node_kernels, node_label)
                           
    # Compute weight matrix of the direct product graph.   
    w_times, w_dim = computeW(g1, g2, vk_dict, ds_attrs,
                              edge_kernels, edge_label)                                                            
    # use uniform distribution if there is no prior knowledge.
    p_times_uni = 1 / w_dim
    A = identity(w_times.shape[0]) - w_times * lmda
    b = np.full((w_dim, 1), p_times_uni)
    x, _ = cg(A, b)
    # use uniform distribution if there is no prior knowledge.
    q_times = np.full((1, w_dim), p_times_uni)
    return np.dot(q_times, x)


###############################################################################
def _fixed_point(Gn, lmda, p, q, ds_attrs, node_kernels, edge_kernels, 
                         node_label, edge_label, eweight, n_jobs):
    """Calculate walk graph kernels up to n between 2 graphs using Fixed-Point method.

    Parameters
    ----------
    G1, G2 : NetworkX graph
        Graphs between which the kernel is calculated.
    node_label : string
        node attribute used as label.
    edge_label : string
        edge attribute used as label.

    Return
    ------
    kernel : float
        Kernel between 2 graphs.
    """
    

    Kmatrix = np.zeros((len(Gn), len(Gn)))
    
#    if not ds_attrs['node_labeled'] and ds_attrs['node_attr_dim'] < 1 and \
#        not ds_attrs['edge_labeled'] and ds_attrs['edge_attr_dim'] > 1:
#        # this is faster from unlabeled graphs. @todo: why?
#        if q == None:
#            # don't normalize adjacency matrices if q is a uniform vector. Note
#            # A_wave_list accually contains the transposes of the adjacency matrices.
#            A_wave_list = [
#                nx.adjacency_matrix(G, eweight).todense().transpose() for G in 
#                    tqdm(Gn, desc='compute adjacency matrices', file=sys.stdout)
#            ]
#            if p == None: # p is uniform distribution as default.
#                pbar = tqdm(
#                    total=(1 + len(Gn)) * len(Gn) / 2,
#                    desc='calculating kernels',
#                    file=sys.stdout)
#                for i in range(0, len(Gn)):
#                    for j in range(i, len(Gn)):                   
#                        # use uniform distribution if there is no prior knowledge.
#                        nb_pd = len(A_wave_list[i]) * len(A_wave_list[j])
#                        p_times_uni = 1 / nb_pd
#                        w_times = kron(A_wave_list[i], A_wave_list[j]).todense()
#                        p_times = np.full((nb_pd, 1), p_times_uni)
#                        x = fixed_point(func_fp, p_times, args=(p_times, lmda, w_times))
#                        # use uniform distribution if there is no prior knowledge.
#                        q_times = np.full((1, nb_pd), p_times_uni)
#                        Kmatrix[i][j] = np.dot(q_times, x)
#                        Kmatrix[j][i] = Kmatrix[i][j]
#                        pbar.update(1)
#    else:  
    # reindex nodes using consecutive integers for convenience of kernel calculation.
    Gn = [nx.convert_node_labels_to_integers(
            g, first_label=0, label_attribute='label_orignal') for g in tqdm(
                Gn, desc='reindex vertices', file=sys.stdout)]
    
    if p == None and q == None: # p and q are uniform distributions as default.
        def init_worker(gn_toshare):
            global G_gn
            G_gn = gn_toshare
        do_partial = partial(wrapper_fp_labled_do, ds_attrs, node_kernels, 
                             node_label, edge_kernels, edge_label, lmda)   
        parallel_gm(do_partial, Kmatrix, Gn, init_worker=init_worker, 
                    glbv=(Gn,), n_jobs=n_jobs)
    return Kmatrix


def wrapper_fp_labled_do(ds_attrs, node_kernels, node_label, edge_kernels, 
                         edge_label, lmda, itr):
    i = itr[0]
    j = itr[1]
    return i, j, _fp_labled_do(G_gn[i], G_gn[j], ds_attrs, node_kernels, 
                               node_label, edge_kernels, edge_label, lmda)


def _fp_labled_do(g1, g2, ds_attrs, node_kernels, node_label, 
                  edge_kernels, edge_label, lmda):
    # Frist, ompute kernels between all pairs of nodes, method borrowed
    # from FCSP. It is faster than directly computing all edge kernels 
    # when $d_1d_2>2$, where $d_1$ and $d_2$ are vertex degrees of the
    # graphs compared, which is the most case we went though. For very 
    # sparse graphs, this would be slow.
    vk_dict = computeVK(g1, g2, ds_attrs, node_kernels, node_label)
                           
    # Compute weight matrix of the direct product graph.   
    w_times, w_dim = computeW(g1, g2, vk_dict, ds_attrs,
                              edge_kernels, edge_label)                                                            
    # use uniform distribution if there is no prior knowledge.
    p_times_uni = 1 / w_dim
    p_times = np.full((w_dim, 1), p_times_uni)
    x = fixed_point(func_fp, p_times, args=(p_times, lmda, w_times),
                    xtol=1e-06, maxiter=1000)
    # use uniform distribution if there is no prior knowledge.
    q_times = np.full((1, w_dim), p_times_uni)
    return np.dot(q_times, x)


def func_fp(x, p_times, lmda, w_times):
    haha = w_times * x
    haha = lmda * haha
    haha = p_times + haha
    return p_times + lmda * np.dot(w_times, x)


###############################################################################
def _spectral_decomposition(Gn, weight, p, q, sub_kernel, eweight, n_jobs):
    """Calculate walk graph kernels up to n between 2 unlabeled graphs using 
    spectral decomposition method. Labels will be ignored.

    Parameters
    ----------
    G1, G2 : NetworkX graph
        Graphs between which the kernel is calculated.
    node_label : string
        node attribute used as label.
    edge_label : string
        edge attribute used as label.

    Return
    ------
    kernel : float
        Kernel between 2 graphs.
    """
    Kmatrix = np.zeros((len(Gn), len(Gn)))

    if q == None:
        # precompute the spectral decomposition of each graph.
        P_list = []
        D_list = []
        for G in tqdm(Gn, desc='spectral decompose', file=sys.stdout):
            # don't normalize adjacency matrices if q is a uniform vector. Note
            # A accually is the transpose of the adjacency matrix.
            A = nx.adjacency_matrix(G, eweight).todense().transpose()
            ew, ev = np.linalg.eig(A)
            D_list.append(ew)
            P_list.append(ev)
#        P_inv_list = [p.T for p in P_list] # @todo: also works for directed graphs?

        if p == None: # p is uniform distribution as default.            
            q_T_list = [np.full((1, nx.number_of_nodes(G)), 1 / nx.number_of_nodes(G)) for G in Gn]
#            q_T_list = [q.T for q in q_list]
            def init_worker(q_T_toshare, P_toshare, D_toshare):
                global G_q_T, G_P, G_D 
                G_q_T = q_T_toshare
                G_P = P_toshare
                G_D = D_toshare
            do_partial = partial(wrapper_sd_do, weight, sub_kernel)   
            parallel_gm(do_partial, Kmatrix, Gn, init_worker=init_worker, 
                        glbv=(q_T_list, P_list, D_list), n_jobs=n_jobs)
            
            
#            pbar = tqdm(
#                total=(1 + len(Gn)) * len(Gn) / 2,
#                desc='calculating kernels',
#                file=sys.stdout)
#            for i in range(0, len(Gn)):
#                for j in range(i, len(Gn)):
#                    result = _sd_do(q_T_list[i], q_T_list[j], P_list[i], P_list[j], 
#                                    D_list[i], D_list[j], weight, sub_kernel)
#                    Kmatrix[i][j] = result
#                    Kmatrix[j][i] = Kmatrix[i][j]
#                    pbar.update(1)
    return Kmatrix


def wrapper_sd_do(weight, sub_kernel, itr):
    i = itr[0]
    j = itr[1]
    return i, j, _sd_do(G_q_T[i], G_q_T[j], G_P[i], G_P[j], G_D[i], G_D[j], 
                        weight, sub_kernel)


def _sd_do(q_T1, q_T2, P1, P2, D1, D2, weight, sub_kernel):    
    # use uniform distribution if there is no prior knowledge.
    kl = kron(np.dot(q_T1, P1), np.dot(q_T2, P2)).todense()
    # @todo: this is not be needed when p = q (kr = kl.T) for undirected graphs
#    kr = kron(np.dot(P_inv_list[i], q_list[i]), np.dot(P_inv_list[j], q_list[j])).todense()
    if sub_kernel == 'exp':
        D_diag = np.array([d1 * d2 for d1 in D1 for d2 in D2])
        kmiddle = np.diag(np.exp(weight * D_diag))
    elif sub_kernel == 'geo':
        D_diag = np.array([d1 * d2 for d1 in D1 for d2 in D2])
        kmiddle = np.diag(weight * D_diag)
        kmiddle = np.identity(len(kmiddle)) - weight * kmiddle
        kmiddle = np.linalg.inv(kmiddle)
    return np.dot(np.dot(kl, kmiddle), kl.T)[0, 0]


###############################################################################
def _randomwalkkernel_kron(G1, G2, node_label, edge_label):
    """Calculate walk graph kernels up to n between 2 graphs using nearest Kronecker product approximation method.

    Parameters
    ----------
    G1, G2 : NetworkX graph
        Graphs between which the kernel is calculated.
    node_label : string
        node attribute used as label.
    edge_label : string
        edge attribute used as label.

    Return
    ------
    kernel : float
        Kernel between 2 graphs.
    """
    pass


###############################################################################
def getLabels(Gn, node_label, edge_label, directed):
    """Get symbolic labels of a graph dataset, where vertex labels are dealt
    with by concatenating them to the edge labels of adjacent edges.
    """
    label_list = []
    label_set = set()
    for g in Gn:
        label_g = {}
        for e in g.edges(data=True):
            nl1 = g.node[e[0]][node_label]
            nl2 = g.node[e[1]][node_label]
            if not directed and nl1 > nl2:
                nl1, nl2 = nl2, nl1
            label = (nl1, e[2][edge_label], nl2)
            label_g[(e[0], e[1])] = label
        label_list.append(label_g)  
    label_set = set([l for lg in label_list for l in lg.values()])
    return label_list, len(label_set)


def filterGramMatrix(gmt, label_dict, label, directed):
    """Compute (the transpose of) the Gram matrix filtered by a label.
    """
    gmf = np.zeros(gmt.shape)
    for (n1, n2), l in label_dict.items():
        if l == label:
            gmf[n2, n1] = gmt[n2, n1]
            if not directed:
                gmf[n1, n2] = gmt[n1, n2]
    return gmf


def computeVK(g1, g2, ds_attrs, node_kernels, node_label):
    '''Compute vertex kernels between vertices of two graphs.
    '''
    vk_dict = {}  # shortest path matrices dict
    if ds_attrs['node_labeled']:
        # node symb and non-synb labeled
        if ds_attrs['node_attr_dim'] > 0:
            kn = node_kernels['mix']
            for n1 in g1.nodes(data=True):
                for n2 in g2.nodes(data=True):
                    vk_dict[(n1[0], n2[0])] = kn(
                        n1[1][node_label], n2[1][node_label],
                        n1[1]['attributes'], n2[1]['attributes'])
        # node symb labeled
        else:
            kn = node_kernels['symb']
            for n1 in g1.nodes(data=True):
                for n2 in g2.nodes(data=True):
                    vk_dict[(n1[0], n2[0])] = kn(n1[1][node_label],
                                                 n2[1][node_label])
    else:
        # node non-synb labeled
        if ds_attrs['node_attr_dim'] > 0:
            kn = node_kernels['nsymb']
            for n1 in g1.nodes(data=True):
                for n2 in g2.nodes(data=True):
                    vk_dict[(n1[0], n2[0])] = kn(n1[1]['attributes'],
                                                 n2[1]['attributes'])
        # node unlabeled
        else:
            pass
    return vk_dict


def computeW(g1, g2, vk_dict, ds_attrs, edge_kernels, edge_label):
    '''Compute weight matrix of the direct product graph.
    '''
    w_dim = nx.number_of_nodes(g1) * nx.number_of_nodes(g2)
    w_times = np.zeros((w_dim, w_dim))
    if vk_dict: # node labeled
        if ds_attrs['is_directed']:
            if ds_attrs['edge_labeled']:
                # edge symb and non-synb labeled
                if ds_attrs['edge_attr_dim'] > 0:
                    ke = edge_kernels['mix']
                    for e1 in g1.edges(data=True):
                        for e2 in g2.edges(data=True):
                            ek_temp = ke(e1[2][edge_label], e2[2][edge_label],
                                         e1[2]['attributes'], e2[2]['attributes'])
                            w_idx = (e1[0] * nx.number_of_nodes(g2) + e2[0],
                                     e1[1] * nx.number_of_nodes(g2) + e2[1])
                            w_times[w_idx] = vk_dict[(e1[0], e2[0])] \
                                * ek_temp * vk_dict[(e1[1], e2[1])]
                # edge symb labeled
                else:
                    ke = edge_kernels['symb']
                    for e1 in g1.edges(data=True):
                        for e2 in g2.edges(data=True):
                            ek_temp = ke(e1[2][edge_label], e2[2][edge_label])
                            w_idx = (e1[0] * nx.number_of_nodes(g2) + e2[0],
                                     e1[1] * nx.number_of_nodes(g2) + e2[1])
                            w_times[w_idx] = vk_dict[(e1[0], e2[0])] \
                                * ek_temp * vk_dict[(e1[1], e2[1])]
            else:
                # edge non-synb labeled
                if ds_attrs['edge_attr_dim'] > 0:
                    ke = edge_kernels['nsymb']
                    for e1 in g1.edges(data=True):
                        for e2 in g2.edges(data=True):
                            ek_temp = ke(e1[2]['attributes'], e2[2]['attributes'])
                            w_idx = (e1[0] * nx.number_of_nodes(g2) + e2[0],
                                     e1[1] * nx.number_of_nodes(g2) + e2[1])
                            w_times[w_idx] = vk_dict[(e1[0], e2[0])] \
                                * ek_temp * vk_dict[(e1[1], e2[1])]
                # edge unlabeled
                else:
                    for e1 in g1.edges(data=True):
                        for e2 in g2.edges(data=True):
                            w_idx = (e1[0] * nx.number_of_nodes(g2) + e2[0],
                                     e1[1] * nx.number_of_nodes(g2) + e2[1])
                            w_times[w_idx] = vk_dict[(e1[0], e2[0])] \
                                * vk_dict[(e1[1], e2[1])]                                
        else: # undirected
            if ds_attrs['edge_labeled']:
                # edge symb and non-synb labeled
                if ds_attrs['edge_attr_dim'] > 0:
                    ke = edge_kernels['mix']
                    for e1 in g1.edges(data=True):
                        for e2 in g2.edges(data=True):
                            ek_temp = ke(e1[2][edge_label], e2[2][edge_label],
                                         e1[2]['attributes'], e2[2]['attributes'])
                            w_idx = (e1[0] * nx.number_of_nodes(g2) + e2[0],
                                     e1[1] * nx.number_of_nodes(g2) + e2[1])
                            w_times[w_idx] = vk_dict[(e1[0], e2[0])] \
                                * ek_temp * vk_dict[(e1[1], e2[1])] \
                                + vk_dict[(e1[0], e2[1])] \
                                * ek_temp * vk_dict[(e1[1], e2[0])]
                            w_times[w_idx[1], w_idx[0]] = w_times[w_idx[0], w_idx[1]]
                            w_idx2 = (e1[0] * nx.number_of_nodes(g2) + e2[1],
                                     e1[1] * nx.number_of_nodes(g2) + e2[0])
                            w_times[w_idx2[0], w_idx2[1]] = w_times[w_idx[0], w_idx[1]]
                            w_times[w_idx2[1], w_idx2[0]] = w_times[w_idx[0], w_idx[1]]
                # edge symb labeled
                else:
                    ke = edge_kernels['symb']
                    for e1 in g1.edges(data=True):
                        for e2 in g2.edges(data=True):
                            ek_temp = ke(e1[2][edge_label], e2[2][edge_label])
                            w_idx = (e1[0] * nx.number_of_nodes(g2) + e2[0],
                                     e1[1] * nx.number_of_nodes(g2) + e2[1])
                            w_times[w_idx] = vk_dict[(e1[0], e2[0])] \
                                * ek_temp * vk_dict[(e1[1], e2[1])] \
                                + vk_dict[(e1[0], e2[1])] \
                                * ek_temp * vk_dict[(e1[1], e2[0])]
                            w_times[w_idx[1], w_idx[0]] = w_times[w_idx[0], w_idx[1]]
                            w_idx2 = (e1[0] * nx.number_of_nodes(g2) + e2[1],
                                     e1[1] * nx.number_of_nodes(g2) + e2[0])
                            w_times[w_idx2[0], w_idx2[1]] = w_times[w_idx[0], w_idx[1]]
                            w_times[w_idx2[1], w_idx2[0]] = w_times[w_idx[0], w_idx[1]]
            else:
                # edge non-synb labeled
                if ds_attrs['edge_attr_dim'] > 0:
                    ke = edge_kernels['nsymb']
                    for e1 in g1.edges(data=True):
                        for e2 in g2.edges(data=True):
                            ek_temp = ke(e1[2]['attributes'], e2[2]['attributes'])
                            w_idx = (e1[0] * nx.number_of_nodes(g2) + e2[0],
                                     e1[1] * nx.number_of_nodes(g2) + e2[1])
                            w_times[w_idx] = vk_dict[(e1[0], e2[0])] \
                                * ek_temp * vk_dict[(e1[1], e2[1])] \
                                + vk_dict[(e1[0], e2[1])] \
                                * ek_temp * vk_dict[(e1[1], e2[0])]
                            w_times[w_idx[1], w_idx[0]] = w_times[w_idx[0], w_idx[1]]
                            w_idx2 = (e1[0] * nx.number_of_nodes(g2) + e2[1],
                                     e1[1] * nx.number_of_nodes(g2) + e2[0])
                            w_times[w_idx2[0], w_idx2[1]] = w_times[w_idx[0], w_idx[1]]
                            w_times[w_idx2[1], w_idx2[0]] = w_times[w_idx[0], w_idx[1]]
                # edge unlabeled
                else:
                    for e1 in g1.edges(data=True):
                        for e2 in g2.edges(data=True):
                            w_idx = (e1[0] * nx.number_of_nodes(g2) + e2[0],
                                     e1[1] * nx.number_of_nodes(g2) + e2[1])
                            w_times[w_idx] = vk_dict[(e1[0], e2[0])] \
                                * vk_dict[(e1[1], e2[1])] \
                                + vk_dict[(e1[0], e2[1])] \
                                * vk_dict[(e1[1], e2[0])]
                            w_times[w_idx[1], w_idx[0]] = w_times[w_idx[0], w_idx[1]]
                            w_idx2 = (e1[0] * nx.number_of_nodes(g2) + e2[1],
                                     e1[1] * nx.number_of_nodes(g2) + e2[0])
                            w_times[w_idx2[0], w_idx2[1]] = w_times[w_idx[0], w_idx[1]]
                            w_times[w_idx2[1], w_idx2[0]] = w_times[w_idx[0], w_idx[1]]
    else: # node unlabeled
        if ds_attrs['is_directed']:
            if ds_attrs['edge_labeled']:
                # edge symb and non-synb labeled
                if ds_attrs['edge_attr_dim'] > 0:
                    ke = edge_kernels['mix']
                    for e1 in g1.edges(data=True):
                        for e2 in g2.edges(data=True):
                            ek_temp = ke(e1[2][edge_label], e2[2][edge_label],
                                         e1[2]['attributes'], e2[2]['attributes'])
                            w_idx = (e1[0] * nx.number_of_nodes(g2) + e2[0],
                                     e1[1] * nx.number_of_nodes(g2) + e2[1])
                            w_times[w_idx] = ek_temp
                # edge symb labeled
                else:
                    ke = edge_kernels['symb']
                    for e1 in g1.edges(data=True):
                        for e2 in g2.edges(data=True):
                            ek_temp = ke(e1[2][edge_label], e2[2][edge_label])
                            w_idx = (e1[0] * nx.number_of_nodes(g2) + e2[0],
                                     e1[1] * nx.number_of_nodes(g2) + e2[1])
                            w_times[w_idx] = ek_temp
            else:
                # edge non-synb labeled
                if ds_attrs['edge_attr_dim'] > 0:
                    ke = edge_kernels['nsymb']
                    for e1 in g1.edges(data=True):
                        for e2 in g2.edges(data=True):
                            ek_temp = ke(e1[2]['attributes'], e2[2]['attributes'])
                            w_idx = (e1[0] * nx.number_of_nodes(g2) + e2[0],
                                     e1[1] * nx.number_of_nodes(g2) + e2[1])
                            w_times[w_idx] = ek_temp
                # edge unlabeled
                else:
                    for e1 in g1.edges(data=True):
                        for e2 in g2.edges(data=True):
                            w_idx = (e1[0] * nx.number_of_nodes(g2) + e2[0],
                                     e1[1] * nx.number_of_nodes(g2) + e2[1])
                            w_times[w_idx] = 1                                
        else: # undirected
            if ds_attrs['edge_labeled']:
                # edge symb and non-synb labeled
                if ds_attrs['edge_attr_dim'] > 0:
                    ke = edge_kernels['mix']
                    for e1 in g1.edges(data=True):
                        for e2 in g2.edges(data=True):
                            ek_temp = ke(e1[2][edge_label], e2[2][edge_label],
                                         e1[2]['attributes'], e2[2]['attributes'])
                            w_idx = (e1[0] * nx.number_of_nodes(g2) + e2[0],
                                     e1[1] * nx.number_of_nodes(g2) + e2[1])
                            w_times[w_idx] = ek_temp
                            w_times[w_idx[1], w_idx[0]] = w_times[w_idx[0], w_idx[1]]
                            w_idx2 = (e1[0] * nx.number_of_nodes(g2) + e2[1],
                                     e1[1] * nx.number_of_nodes(g2) + e2[0])
                            w_times[w_idx2[0], w_idx2[1]] = w_times[w_idx[0], w_idx[1]]
                            w_times[w_idx2[1], w_idx2[0]] = w_times[w_idx[0], w_idx[1]]
                # edge symb labeled
                else:
                    ke = edge_kernels['symb']
                    for e1 in g1.edges(data=True):
                        for e2 in g2.edges(data=True):
                            ek_temp = ke(e1[2][edge_label], e2[2][edge_label])
                            w_idx = (e1[0] * nx.number_of_nodes(g2) + e2[0],
                                     e1[1] * nx.number_of_nodes(g2) + e2[1])
                            w_times[w_idx] = ek_temp
                            w_times[w_idx[1], w_idx[0]] = w_times[w_idx[0], w_idx[1]]
                            w_idx2 = (e1[0] * nx.number_of_nodes(g2) + e2[1],
                                     e1[1] * nx.number_of_nodes(g2) + e2[0])
                            w_times[w_idx2[0], w_idx2[1]] = w_times[w_idx[0], w_idx[1]]
                            w_times[w_idx2[1], w_idx2[0]] = w_times[w_idx[0], w_idx[1]]
            else:
                # edge non-synb labeled
                if ds_attrs['edge_attr_dim'] > 0:
                    ke = edge_kernels['nsymb']
                    for e1 in g1.edges(data=True):
                        for e2 in g2.edges(data=True):
                            ek_temp = ke(e1[2]['attributes'], e2[2]['attributes'])
                            w_idx = (e1[0] * nx.number_of_nodes(g2) + e2[0],
                                     e1[1] * nx.number_of_nodes(g2) + e2[1])
                            w_times[w_idx] = ek_temp
                            w_times[w_idx[1], w_idx[0]] = w_times[w_idx[0], w_idx[1]]
                            w_idx2 = (e1[0] * nx.number_of_nodes(g2) + e2[1],
                                     e1[1] * nx.number_of_nodes(g2) + e2[0])
                            w_times[w_idx2[0], w_idx2[1]] = w_times[w_idx[0], w_idx[1]]
                            w_times[w_idx2[1], w_idx2[0]] = w_times[w_idx[0], w_idx[1]]
                # edge unlabeled
                else:
                    for e1 in g1.edges(data=True):
                        for e2 in g2.edges(data=True):
                            w_idx = (e1[0] * nx.number_of_nodes(g2) + e2[0],
                                     e1[1] * nx.number_of_nodes(g2) + e2[1])
                            w_times[w_idx] = 1
                            w_times[w_idx[1], w_idx[0]] = w_times[w_idx[0], w_idx[1]]
                            w_idx2 = (e1[0] * nx.number_of_nodes(g2) + e2[1],
                                     e1[1] * nx.number_of_nodes(g2) + e2[0])
                            w_times[w_idx2[0], w_idx2[1]] = w_times[w_idx[0], w_idx[1]]
                            w_times[w_idx2[1], w_idx2[0]] = w_times[w_idx[0], w_idx[1]]
    return w_times, w_dim