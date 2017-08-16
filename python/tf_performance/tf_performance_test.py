#!/usr/bin/env python
from __future__ import print_function

import os
import argparse
import threading
import Queue
import numpy as np
import tensorflow as tf
import tensorflow.contrib.layers as tf_layers
from tensorflow.python.client import timeline
from RLrecon.utils import Timer


class DataProvider(object):

    def __init__(self, epoch_generator_factory,
                 num_epochs=-1):
        self._epoch_generator_factory = epoch_generator_factory
        self._num_epochs = num_epochs

        self._batch_queue = Queue.Queue(20000)
        self._epoch = 0
        self._batch_count = 0
        self._record_count = 0

        self._thread = None

    def _run(self):
        """Thread loop. Feeds new data into queue."""
        def enqueue_epoch():
            epoch_generator = self._epoch_generator_factory()
            for record_batch in epoch_generator:
                self._batch_queue.put(record_batch)
            self._batch_queue.put(None)
        if self._num_epochs <= 0:
            while True:
                enqueue_epoch()
        else:
            for i in xrange(self._num_epochs):
                enqueue_epoch()

    def start_thread(self):
        """Start thread to fill queue """
        assert(self._thread is None)
        self._batch_count = 0
        self._record_count = 0
        self._thread = threading.Thread(target=self._run)
        self._thread.daemon = True  # Kill thread when all other threads stopped
        self._thread.start()
        return self._thread

    def join_thread(self):
        self._thread.join()
        self._thread = None

    def next_batch(self):
        record_batch = self._batch_queue.get()
        if record_batch is None:
            self._epoch += 1
            return None
        self._batch_count += 1
        self._record_count += record_batch[0].shape[0]
        return record_batch

    def get_queue_size(self):
        return self._batch_queue.qsize()

    def get_epoch(self):
        return self._epoch

    def get_batch_count(self):
        return self._batch_count

    def get_record_count(self):
        return self._record_count


def create_epoch_batch_generator(batch_size, data_size, epoch_size):
    for epoch in xrange(epoch_size):
        batch = np.random.rand(batch_size, *data_size)
        label = np.random.randint(0, 2, batch_size)
        yield batch, label


def flatten(x):
    return tf.reshape(x, [-1, np.prod(x.get_shape().as_list()[1:])])


def run(args):
    create_tf_timeline = False
    num_epochs = 10000
    epoch_size = 1000
    batch_size = 64
    data_size = [16, 16, 16, 2]

    # epoch_generator_factory = lambda: create_epoch_generator(train_filenames, grid_3d_mask)
    epoch_generator_factory = lambda: create_epoch_batch_generator(batch_size, data_size, epoch_size)
    with tf.device("/cpu:0"):
        # data_provider = TFDataProvider(epoch_generator_factory, batch_size, grid_3d_shape)
        data_provider = DataProvider(epoch_generator_factory)
    data_provider.start_thread()

    # device_name = '/cpu:0'
    device_name = '/gpu:0'
    with tf.device(device_name):
        in_tf = tf.placeholder(tf.float32, shape=[None] + data_size, name="in")
        with tf.variable_scope("model"):
            in_flat = flatten(in_tf)
            num_outputs = 1024
            x = tf_layers.fully_connected(in_flat, num_outputs, tf.nn.relu)
            x = tf_layers.fully_connected(x, num_outputs, tf.nn.relu)
            x = tf_layers.fully_connected(x, num_outputs, tf.nn.relu)
            x = tf_layers.fully_connected(x, num_outputs, tf.nn.relu)
            x = tf_layers.fully_connected(x, num_outputs, tf.nn.relu)
            output = tf_layers.fully_connected(x, 1)
            variables = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, tf.get_variable_scope().name)

        # Generate ground-truth inputs for computing loss function
        labels = tf.placeholder(dtype=np.float32, shape=[None], name="labels")

        loss_batch = tf.square(output - labels, name="loss_batch")
        loss = tf.reduce_mean(loss_batch, name="loss")
        loss_min = tf.reduce_min(loss_batch, name="loss_min")
        loss_max = tf.reduce_max(loss_batch, name="loss_max")

    gradients = tf.gradients(loss, variables)
    # Create optimizer
    opt = tf.train.AdamOptimizer()
    train_op = opt.minimize(loss, var_list=variables)

    # Configure tensorflow
    config = tf.ConfigProto()
    config.gpu_options.per_process_gpu_memory_fraction = 0.3
    config.intra_op_parallelism_threads = 1
    config.inter_op_parallelism_threads = 1
    # config.log_device_placement = True

    # Initialize tensorflow session
    if create_tf_timeline:
        run_metadata = tf.RunMetadata()
    else:
        run_metadata = None
    sess = tf.Session(config=config)
    init = tf.global_variables_initializer()
    sess.run(init)
    tf.train.start_queue_runners(sess=sess)
    # data_provider.start_thread(sess)

    timer = Timer()
    if create_tf_timeline:
        train_options = tf.RunOptions(timeout_in_ms=100000,
                                      trace_level=tf.RunOptions.FULL_TRACE)
    else:
        train_options = None
    for epoch in xrange(num_epochs):
        compute_time = 0.0
        data_time = 0.0
        total_loss_value = 0.0
        total_loss_min = +np.finfo(np.float32).max
        total_loss_max = -np.finfo(np.float32).max
        batch_count = 0
        assert(epoch == data_provider.get_epoch())
        while True:
            t1 = timer.elapsed_seconds()
            record_batch = data_provider.next_batch()
            if record_batch is None:
                break
            t2 = timer.elapsed_seconds()
            data_time += t2 - t1
            # _, loss_value = sess.run([train_op, loss], options=train_options)
            t1 = timer.elapsed_seconds()
            fetched =\
                sess.run([train_op, loss, loss_min, loss_max],
                         options=train_options, run_metadata=run_metadata, feed_dict={
                    in_tf: record_batch[0],
                    labels: record_batch[1],
            })
            _, loss_v, loss_min_v, loss_max_v = fetched[:4]
            if create_tf_timeline:
                trace = timeline.Timeline(step_stats=run_metadata.step_stats)
                with open('timeline.ctf.json', 'w') as trace_file:
                    trace_file.write(trace.generate_chrome_trace_format())

            total_loss_value += loss_v
            total_loss_min = np.minimum(loss_min_v, total_loss_min)
            total_loss_max = np.maximum(loss_max_v, total_loss_max)
            t2 = timer.elapsed_seconds()
            compute_time += t2 - t1
            # record_count = data_provider.get_record_count()
            # batch_count = data_provider.get_batch_count()
            # if (record_count + 1) % report_step_interval == 0:
            #     print("batches: {}, record count: {}, data_time: {}, compute_time: {}".format(
            #         batch_count, record_count,
            #         data_time, compute_time))
            # epoch_done = data_provider.consume_batch()
            batch_count += 1
            # print("queue size:", data_provider.get_queue_size())
        # record_count = data_provider.get_record_count()
        # batch_count = data_provider.get_batch_count()
        total_loss_value /= batch_count
        print("train result:")
        print("  epoch: {}, loss: {}, min loss: {}, max loss: {}".format(
            epoch, total_loss_value, total_loss_min, total_loss_max))
        print("train timing:")
        print("  batches: {}, data time: {}, compute time: {}".format(
            batch_count, data_time, compute_time))

        # epoch_generator = create_epoch_generator(train_filenames, batch_size)
        # t1 = timer.elapsed_seconds()
        # record_count = 0
        # for batch_idx, record_batch in enumerate(epoch_generator):
        #     # grid_3d_batch = record_batch.grid_3ds[:, obs_levels_to_use, ...]
        #     grid_3d_batch = record_batch.grid_3ds[..., grid_3d_mask]
        #     # TODO: Gradient should be scaled to batch size, though this is a minor thing.
        #     # for record in records:
        #     #     print("  ", record.action, record.reward)
        #     t2 = timer.elapsed_seconds()
        #     data_time += t2 - t1
        #     _, loss_value = sess.run([train_op, loss], feed_dict={
        #         gt_rewards: record_batch.rewards,
        #         actions: record_batch.actions,
        #         grid_3d_tf: grid_3d_batch,
        #     })
        #     t1 = timer.elapsed_seconds()
        #     compute_time += t1 - t2
        #     record_count += grid_3d_batch.shape[0]
        #     if (batch_idx + 1) % report_step_interval == 0:
        #         print("batch: {}, record count: {}, data_time: {}, compute_time: {}".format(
        #             batch_idx, record_count, data_time, compute_time))

    data_provider.join_thread()


if __name__ == '__main__':
    np.set_printoptions(threshold=5)

    parser = argparse.ArgumentParser(description=None)
    args = parser.parse_args()

    run(args)
