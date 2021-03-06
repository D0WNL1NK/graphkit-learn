# -*- coding: utf-8 -*-
"""compute_distance_in_kernel_space.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/17tZP6IrineQmzo9sRtfZOnHpHx6HnlMA

**This script demonstrates how to compute distance in kernel space between the image of a graph and the mean of images of a group of graphs.**
---

**0.   Install `graphkit-learn`.**
"""

"""**1.   Get dataset.**"""

from gklearn.utils import Dataset

# Predefined dataset name, use dataset "MUTAG".
ds_name = 'MUTAG'

# Initialize a Dataset.
dataset = Dataset()
# Load predefined dataset "MUTAG".
dataset.load_predefined_dataset(ds_name)
len(dataset.graphs)

"""**2.  Compute graph kernel.**"""

from gklearn.kernels import PathUpToH
import multiprocessing

# Initailize parameters for graph kernel computation.
kernel_options = {'depth': 3,
				  'k_func': 'MinMax',
				  'compute_method': 'trie'
				  }

# Initialize graph kernel.
graph_kernel = PathUpToH(node_labels=dataset.node_labels, # list of node label names.
						 edge_labels=dataset.edge_labels, # list of edge label names.
						 ds_infos=dataset.get_dataset_infos(keys=['directed']), # dataset information required for computation.
						 **kernel_options, # options for computation.
						 )

# Compute Gram matrix.
gram_matrix, run_time = graph_kernel.compute(dataset.graphs,
											 parallel='imap_unordered', # or None.
											 n_jobs=multiprocessing.cpu_count(), # number of parallel jobs.
											 normalize=True, # whether to return normalized Gram matrix.
											 verbose=2 # whether to print out results.
                                            )

"""**3.   Compute distance in kernel space.**

Given a dataset $\mathcal{G}_N$, compute the distance in kernel space between the image of $G_1 \in \mathcal{G}_N$ and the mean of images of $\mathcal{G}_k \subset \mathcal{G}_N$.
"""

from gklearn.preimage.utils import compute_k_dis

# Index of $G_1$.
idx_1 = 10
# Indices of graphs in $\mathcal{G}_k$.
idx_graphs = range(0, 10)

# Compute the distance in kernel space.
dis_k = compute_k_dis(idx_1,
                      idx_graphs,
					  [1 / len(idx_graphs)] * len(idx_graphs), # weights for images of graphs in $\mathcal{G}_k$; all equal when computing the mean.
					  gram_matrix, # gram matrix of al graphs.
					  withterm3=False
					  )
print(dis_k)