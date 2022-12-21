from collections import defaultdict

import matplotlib.pyplot as plt

# algorithms
algos = ['HEFTAddEnd', 'HEFTAddBetween', 'Topological',
         'Genetic[generations=50,size_selection=None,mutate_order=None,mutate_resources=None]']

# algo -> blocks received
global_algo_frequencies = defaultdict(int)
# algo, block type -> blocks received
global_algo_block_type_frequencies = defaultdict(lambda: defaultdict(int))
# algo, block graph type -> blocks received
global_algo_bg_type_frequencies = defaultdict(lambda: defaultdict(int))

# algo -> downtime
global_algo_downtime = defaultdict(int)
# algo, block type -> downtime
global_algo_block_type_downtime = defaultdict(lambda: defaultdict(int))
# algo, block graph type -> downtime
global_algo_bg_type_downtime = defaultdict(lambda: defaultdict(int))

run_mode_index = 0


algo_labels = ['HEFTAddEnd', 'HEFTAddBetween', 'Topological',
               'GeneticScheduler[\ngenerations=50,size_selection=None,\nmutate_order=None,mutate_resources=None]']


for run_index in range(5):
    with open(f'algorithms_comparison_block_size_{run_mode_index}_{run_index}.txt', 'r') as f:
        mode = None
        finished = True
        bg_info_read = False
        bg_info = []
        downtimes = []
        i = 0  # index of algorithm
        iter = 0  # index of iteration

        for line in f.readlines():
            line = line.strip()
            if finished:
                # skip lines between blocks
                if len(line) == 0:
                    continue
                finished = False
                bg_info_read = False

                iter += 1
                if iter == 1:
                    mode = line
                else:
                    bg_info = line.split(' ')
                    bg_info_read = True
                    if iter == 4:
                        iter = 0

                i = 0
                continue
            if not bg_info_read:
                # read bg type and block types
                bg_info = line.split(' ')
                bg_info_read = True
                continue
            if i == 10 or (i == 7 and bg_info[0] == 'Queues'):
                finished = True
                downtimes = [int(downtime) for downtime in line.split(' ')]
                for algo_ind, algo in enumerate(algos):
                    global_algo_downtime[algo] += downtimes[algo_ind]
                i += 1
                continue

            # in this place the line = algo name
            algo = line.replace('Scheduler', '')
            # grab statistics
            global_algo_frequencies[algo] += 1
            global_algo_bg_type_frequencies[bg_info[0]][algo] += 1
            if len(bg_info) != 1:
                global_algo_block_type_frequencies[algo][bg_info[i + 1]] += 1
            i += 1

# plt.subplots_adjust(top=100, wspace=.5, hspace=.5)

# general comparison
# algo_labels = list(global_algo_frequencies.keys())
algo_freq = list(global_algo_frequencies.values())

centers = range(len(algo_labels))
_, ax = plt.subplots(figsize=(10, 7))
ax.bar(centers, algo_freq, tick_label=algo_labels)
plt.suptitle('Algorithms block receive count', fontsize=24)

plt.show()

# block graph type comparison
fig = plt.figure(figsize=(14, 10))
fig.suptitle('Algorithms with graph types comparison', fontsize=32)

freq = list(global_algo_bg_type_frequencies.items())[0]
ax1 = fig.add_subplot(221)
ax1.set(title=freq[0], xticks=[], yticks=[])
ax1.bar(range(len(algo_labels)), [freq[1][algo] for algo in algos], tick_label=algo_labels)
freq = list(global_algo_bg_type_frequencies.items())[1]
ax2 = fig.add_subplot(222)
ax2.set(title=freq[0], xticks=[], yticks=[])
ax2.bar(range(len(algo_labels)), [freq[1][algo] for algo in algos], tick_label=algo_labels)
freq = list(global_algo_bg_type_frequencies.items())[2]
ax3 = fig.add_subplot(223)
ax3.set(title=freq[0], xticks=[], yticks=[])
ax3.bar(range(len(algo_labels)), [freq[1][algo] for algo in algos], tick_label=algo_labels)
freq = list(global_algo_bg_type_frequencies.items())[3]
ax4 = fig.add_subplot(224)
ax4.set(title=freq[0], xticks=[], yticks=[])
ax4.bar(range(len(algo_labels)), [freq[1][algo] for algo in algos], tick_label=algo_labels)

plt.subplots_adjust(left=0.1,
                    bottom=0.1,
                    right=0.9,
                    top=0.9,
                    wspace=0.4,
                    hspace=0.4)
plt.show()

# block type comparison
fig = plt.figure(figsize=(14, 10))
fig.suptitle('Algorithms with block types comparison', fontsize=32)
freq = list(global_algo_block_type_frequencies.items())[0]
ax1 = fig.add_subplot(221)
ax1.set(title=algo_labels[0], xticks=[], yticks=[])
ax1.bar(range(len(freq[1])), freq[1].values(), tick_label=list(freq[1].keys()))
freq = list(global_algo_block_type_frequencies.items())[1]
ax2 = fig.add_subplot(222)
ax2.set(title=algo_labels[1], xticks=[], yticks=[])
ax2.bar(range(len(freq[1])), freq[1].values(), tick_label=list(freq[1].keys()))
freq = list(global_algo_block_type_frequencies.items())[2]
ax3 = fig.add_subplot(223)
ax3.set(title=algo_labels[2], xticks=[], yticks=[])
ax3.bar(range(len(freq[1])), freq[1].values(), tick_label=list(freq[1].keys()))
freq = list(global_algo_block_type_frequencies.items())[3]
ax4 = fig.add_subplot(224)
ax4.set(title=algo_labels[3], xticks=[], yticks=[])
ax4.bar(range(len(freq[1])), freq[1].values(), tick_label=list(freq[1].keys()))

plt.subplots_adjust(left=0.1,
                    bottom=0.1,
                    right=0.9,
                    top=0.9,
                    wspace=0.4,
                    hspace=0.4)
plt.show()

