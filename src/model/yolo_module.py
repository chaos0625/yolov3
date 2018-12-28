#!/usr/bin/env python
# -*- coding: utf-8 -*-
# File: yolo_module.py
# Author: Qian Ge <geqian1001@gmail.com>

import tensorflow as tf
import src.model.layers as L

import src.bbox.tfbboxtool as tfbboxtool

def leaky(x):
    return L.leaky_relu(x, leak=0.1)

def yolo_layer(input_feat, n_filter, out_dim, up_sample=False, darknet_feat=None,
               pretrained_dict=None, init_w=None, init_b=tf.zeros_initializer(),
               bn=True, wd=0, trainable=False, is_training=False,
               scale_id=1, name='yolo'):
    
    layer_dict = {}
    layer_dict['cur_input'] = input_feat

    with tf.variable_scope('{}_{}'.format(name, scale_id)):
        arg_scope = tf.contrib.framework.arg_scope
        with arg_scope([L.conv], layer_dict=layer_dict, pretrained_dict=pretrained_dict,
                       bn=bn, nl=leaky, init_w=init_w, wd=wd, is_training=is_training,
                       use_bias=False, trainable=trainable, custom_padding=None):

            if up_sample:
                assert darknet_feat is not None
                L.conv(filter_size=1, out_dim=n_filter // 2, stride=1,
                       name='conv_{}_0'.format(scale_id))
                up_sample_shape = tf.shape(darknet_feat)[1:3]
                up_feat = feat_upsampling_nearest_neighbor(
                    layer_dict['cur_input'], up_shape=up_sample_shape)
                layer_dict['cur_input'] = tf.concat(
                    (up_feat, darknet_feat), axis=-1)

            L.conv(filter_size=1, out_dim=n_filter // 2, stride=1,
                   name='conv_{}_1'.format(scale_id))
            L.conv(filter_size=3, out_dim=n_filter, stride=1,
                   name='conv_{}_2'.format(scale_id))
            L.conv(filter_size=1, out_dim=n_filter // 2, stride=1,
                   name='conv_{}_3'.format(scale_id))
            L.conv(filter_size=3, out_dim=n_filter, stride=1,
                   name='conv_{}_4'.format(scale_id))
            L.conv(filter_size=1, out_dim=n_filter // 2, stride=1,
                   name='conv_{}_5'.format(scale_id))
            L.conv(filter_size=3, out_dim=n_filter, stride=1,
                   name='conv_{}_6'.format(scale_id))

            L.conv(filter_size=1, out_dim=out_dim, stride=1,
                   name='conv_{}_7'.format(scale_id))

        return layer_dict['cur_input'], layer_dict['conv_{}_5'.format(scale_id)]

def yolo_prediction(inputs, anchors, n_class, scale, scale_id=1, name='yolo_prediction'):
    # reference:
    # https://github.com/pjreddie/darknet/blob/master/src/yolo_layer.c#L316
    with tf.name_scope('{}_{}'.format(name, scale_id)):
        shape = tf.shape(inputs)
        y_grid, x_grid = tf.meshgrid(tf.range(shape[1]), tf.range(shape[2]), indexing='ij')
        x_grid_flatten = tf.cast(tf.reshape(x_grid, (1, -1, 1)), tf.float32)
        y_grid_flatten = tf.cast(tf.reshape(y_grid, (1, -1, 1)), tf.float32)
        xy_grid_flatten = tf.concat((x_grid_flatten, y_grid_flatten), axis=-1)

        n_anchors = len(anchors)
        detection_list = tf.split(inputs, n_anchors, axis=-1, name='split_anchor')
        bbox_score = []
        bbox_list = []
        for anchor_id in range(n_anchors):
            cur_bbox = detection_list[anchor_id]
            bbox, objectness, classes = tf.split(
                cur_bbox, [4, 1, n_class], axis=-1, name='split_detection')
            bbox = correct_yolo_boxes(xy_grid_flatten, bbox, anchors[anchor_id], scale)
            objectness = tf.nn.sigmoid(objectness)
            classes =  tf.nn.sigmoid(classes)

            bbox_score.append(tf.multiply(objectness, classes))
            bbox_list.append(bbox)

        bsize = tf.shape(inputs)[0]
        
        bbox_score = tf.stack(bbox_score, axis=0)
        bbox_score = tf.transpose(bbox_score, (1, 0, 2, 3, 4))
        bbox_score = tf.reshape(bbox_score, (bsize, -1, n_class))

        bbox_list = tf.stack(bbox_list, axis=0)
        bbox_list = tf.transpose(bbox_list, (1, 0, 2, 3, 4))
        bbox_list = tf.reshape(bbox_list, (bsize, -1, 4))
        return bbox_score, bbox_list

def correct_yolo_boxes(xy_grid_flatten, bbox, anchor, scale):
    # [bsize, h, w, 4]
    bsize = tf.shape(bbox)[0]
    shape = tf.shape(bbox)
    bbox_flatten = tf.reshape(bbox, (bsize, -1, 4))
    bbox_xy, bbox_wh = tf.split(bbox_flatten, [2, 2], axis=-1)
    bbox_xy = tf.nn.sigmoid(bbox_xy)
    bbox_xy = bbox_xy + xy_grid_flatten

    pw, ph = anchor[0], anchor[1]
    bwh = tf.multiply(anchor, tf.exp(bbox_wh))

    correct_bbox = tf.concat([bbox_xy * scale, bwh], axis=-1)
    return tf.reshape(correct_bbox, (bsize, shape[1], shape[2], 4))

def get_detection(bbox_score, bbox_list, n_class, score_thr, iou_thr,
                  max_boxes=20, rescale_shape=None, original_shape=None):
    # for a single batch
    
    det_score = []
    det_class = []
    det_bbox = []

    if rescale_shape is not None and original_shape is not None:
        bbox_list = tfbboxtool.rescale_bbox(bbox_list, rescale_shape, original_shape)

    xyxy_bbox = tfbboxtool.cxywh2xyxy(bbox_list)

    obj_mask = bbox_score >= score_thr
    for c_idx in range(n_class):
        c_score = tf.boolean_mask(bbox_score[:, c_idx], obj_mask[:, c_idx])
        c_bbox = tf.boolean_mask(xyxy_bbox, obj_mask[:, c_idx])
        nms_idx = tf.image.non_max_suppression(
            boxes=c_bbox,
            scores=c_score,
            max_output_size=max_boxes,
            iou_threshold=iou_thr,
            # score_threshold=score_thr
            )
        c_score = tf.gather(c_score, nms_idx, axis=0)
        c_bbox = tf.gather(c_bbox, nms_idx, axis=0)

        det_score.append(c_score)
        det_bbox.append(c_bbox)
        det_class.append(tf.ones_like(c_score) * c_idx)

    det_score = tf.concat(det_score, axis=0)
    det_bbox = tf.concat(det_bbox, axis=0)
    det_class = tf.concat(det_class, axis=0)

    return det_score, det_bbox, det_class

def feat_upsampling_nearest_neighbor(input_feat, up_shape, name='feat_upsampling'):
    with tf.name_scope(name):
        up_feat = tf.image.resize_nearest_neighbor(
            input_feat, (up_shape[0], up_shape[1]))
        return up_feat
