import os

import numpy as np
import tensorflow as tf
from kungfu.tensorflow.initializer import BroadcastGlobalVariablesOp
from kungfu.tensorflow.ops import (_get_init_step, consensus, counter,
                                   resize_cluster_from_url, step_based_schedule)


class ElasticHook(tf.train.SessionRunHook):
    def __init__(self, max_step):
        self._max_step = max_step
        self._need_sync = True

    def _build_resize_op(self, init_step):
        step = counter(init_step)
        ckpt_tensor = tf.as_string(step + 1)
        resize_op = resize_cluster_from_url(ckpt_tensor)
        return resize_op

    def begin(self):
        self._kungfu_step = tf.Variable(0, trainable=False, dtype=tf.int64)
        self._advance = tf.assign_add(self._kungfu_step, 1)
        self._sync_op = BroadcastGlobalVariablesOp()
        ckpt = _get_init_step()
        self._init_kungfu_step = tf.assign(self._kungfu_step, int(ckpt))
        self._resize_op = self._build_resize_op(int(ckpt))
        self._reset_global_step = tf.assign(tf.train.get_global_step(),
                                            int(ckpt))

    def after_create_session(self, sess, coord):
        sess.run(self._init_kungfu_step)
        sess.run(self._reset_global_step)

    def before_run(self, run_context):
        kungfu_step = run_context.session.run(self._kungfu_step)
        if kungfu_step >= self._max_step:
            print('request_stop before kungfu_step: %d' % (kungfu_step))
            # run_context.request_stop()
            # FIXME: force quit

        if self._need_sync:
            run_context.session.run(self._sync_op)
            self._need_sync = False

    def after_run(self, run_context, run_values):
        kungfu_step = run_context.session.run(self._kungfu_step)
        changed, keep = run_context.session.run(self._resize_op)
        if changed:
            print('changed on %d' % (kungfu_step))
            self._need_sync = True
            if not keep:
                run_context.request_stop()
                return

        kungfu_step = run_context.session.run(self._advance)
        if kungfu_step >= self._max_step:
            print('request_stop on kungfu_step: %d' % (kungfu_step))
            run_context.request_stop()

    def end(self, sess):
        global_step = sess.run(tf.train.get_global_step())
        kungfu_step = sess.run(self._kungfu_step)
        print('stopped at global_step: %d, kungfu_step: %d' %
              (global_step, kungfu_step))