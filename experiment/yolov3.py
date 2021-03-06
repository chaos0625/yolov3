#!/usr/bin/env python
# -*- coding: utf-8 -*-
# File: yolov3.py
# Author: Qian Ge <geqian1001@gmail.com>

import os
import argparse
import platform
import numpy as np
import tensorflow as tf

import sys
sys.path.append('../')
import loader
import configs.parsecfg as parscfg
from src.net.yolov3 import YOLOv3


def get_args():
    parser = argparse.ArgumentParser()

    parser.add_argument('--train', action='store_true',
                        help='Train the model.')
    parser.add_argument('--detect', action='store_true',
                        help='detect')
    parser.add_argument('--lr', type=float, default=0.1,
                        help='Batch size')
    
    return parser.parse_args()

def train():
    FLAGS = get_args()
    config = parscfg.ConfigParser('configs/config_path.cfg',
                                  'configs/voc.cfg')

    label_dict, category_index, train_data_generator, valid_data_generator = loader.load_VOC(
        data_dir=config.train_data_dir,
        rescale_shape_list=config.mutliscale,
        net_stride_list=[32, 16, 8], 
        prior_anchor_list=config.anchors,
        train_percentage=0.85,
        n_class=config.n_class,
        batch_size=config.train_bsize, 
        buffer_size=4,
        num_parallel_preprocess=8,
        h_flip=True, crop=True, color=True, affine=True,
        max_num_bbox_per_im=57)

    # Training
    train_model = YOLOv3(
        n_channel=config.n_channel,
        n_class=config.n_class, 
        category_index=category_index,
        anchors=config.anchors,
        bsize=config.train_bsize, 
        ignore_thr=config.ignore_thr,
        obj_weight=config.obj_weight,
        nobj_weight=config.nobj_weight,
        feature_extractor_trainable=False, 
        detector_trainable=True,
        pre_trained_path=config.yolo_feat_pretrained_path,)
    train_model.create_train_model(train_data_generator.batch_data)

    # Validation
    valid_model = YOLOv3(
        n_channel=config.n_channel,
        n_class=config.n_class, 
        anchors=config.anchors,
        category_index=category_index,
        bsize=config.train_bsize, 
        ignore_thr=config.ignore_thr,
        obj_weight=config.obj_weight,
        nobj_weight=config.nobj_weight,
        feature_extractor_trainable=False, 
        detector_trainable=False,
        pre_trained_path=config.yolo_feat_pretrained_path,)
    valid_model.create_valid_model(valid_data_generator.batch_data)

    #testing
    # test_scale = 416
    # image_data = loader.read_image(
    #     im_name=config.im_name,
    #     n_channel=config.n_channel,
    #     data_dir=config.data_dir,
    #     batch_size=config.test_bsize, 
    #     rescale=test_scale)

    writer = tf.summary.FileWriter(config.save_path)
    saver = tf.train.Saver(max_to_keep=5)
    # saver = tf.train.Saver(
    #     var_list=tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope='style_net'))
    sessconfig = tf.ConfigProto()
    sessconfig.gpu_options.allow_growth = True
    with tf.Session(config=sessconfig) as sess:
        sess.run(tf.global_variables_initializer())
        sess.graph.finalize()
        writer.add_graph(sess.graph)

        for i in range(150):
            if i >= 100:
                lr = FLAGS.lr / 100.
            elif i >= 50:
                lr = FLAGS.lr / 10.
            else:
                lr = FLAGS.lr

            # test_model.predict_epoch_or_step(
            #     sess,
            #     image_data, 
            #     test_scale, 
            #     config.obj_score_thr, 
            #     config.nms_iou_thr,
            #     label_dict, 
            #     category_index, 
            #     config.save_path, 
            #     run_type='epoch')

            if i > 0 and i % 10 == 0:
                train_data_generator.init_iterator(sess, reset_scale=True)
            else:
                train_data_generator.init_iterator(sess, reset_scale=False)

            train_model.train_epoch(sess, lr, summary_writer=writer)

            valid_data_generator.init_iterator(sess)
            valid_model.valid_epoch(sess, summary_writer=writer)

            saver.save(sess, '{}/yolov3_epoch_{}'.format(config.save_path, i))

            # if i > 0 and i % 10 == 0:
            #     train_data_generator.reset_im_scale()

    writer.close()

def detect():
    config = parscfg.ConfigParser('configs/config_path.cfg',
                                  'configs/coco80.cfg')

    label_dict, category_index = loader.load_coco80_label_yolo()
    # Create a Dataflow object for test images
    image_data = loader.read_image(
        im_name=config.im_name,
        n_channel=config.n_channel,
        data_dir=config.data_dir,
        batch_size=config.test_bsize, 
        rescale=config.im_rescale)

    test_model = YOLOv3(
        bsize=config.test_bsize,
        n_channel=config.n_channel,
        n_class=config.n_class, 
        anchors=config.anchors,
        feature_extractor_trainable=False, 
        detector_trainable=False,
        pre_trained_path=config.coco_pretrained_path,)
    test_model.create_test_model()

    sessconfig = tf.ConfigProto()
    sessconfig.gpu_options.allow_growth = True
    with tf.Session(config=sessconfig) as sess:
        sess.run(tf.global_variables_initializer())

        test_model.predict_epoch_or_step(
            sess,
            image_data,
            config.im_rescale,
            config.obj_score_thr, 
            config.nms_iou_thr,
            label_dict, 
            category_index, 
            config.save_path, 
            run_type='epoch')

if __name__ == '__main__':
    FLAGS = get_args()

    if FLAGS.train:
        train()
    if FLAGS.detect:
        detect()
