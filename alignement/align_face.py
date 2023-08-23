"""
brief: face alignment with FFHQ method (https://github.com/NVlabs/ffhq-dataset)
author: lzhbrian (https://lzhbrian.me)
date: 2020.1.5
note: code is heavily borrowed from 
    https://github.com/NVlabs/ffhq-dataset
    http://dlib.net/face_landmark_detection.py.html
requirements:
    # download face landmark model from: 
    # http://dlib.net/files/shape_predictor_68_face_landmarks.dat.bz2
"""

import numpy as np
import PIL
import PIL.Image
import PIL.ImageDraw
import scipy
import scipy.ndimage
import dlib


def get_landmarks(filepath: str, predictor):
    """get landmark with dlib
    :return: np.array shape=(68, 2)
    """
    detector = dlib.get_frontal_face_detector()

    # img = dlib.load_rgb_image(filepath)
    img = np.array(
        PIL.Image.open(filepath)
    )  # changed to loading by pillow which allows practically all image formats
    dets = detector(img, 1)

    print(f"Number of faces detected in {filepath}: {len(dets)}")
    if not len(dets):
        return None

    lms = []
    for k, d in enumerate(dets):
        print(
            f"Detection {k}: Left: {d.left()} Top: {d.top()} Right: {d.right()} Bottom: {d.bottom()}"
        )
        # Get the landmarks/parts for the face in box d.
        shape = predictor(img, d)
        print(f"Part 0: {shape.part(0)}, Part 1: {shape.part(1)} ...")

        t = list(shape.parts())
        a = []
        for tt in t:
            a.append([tt.x, tt.y])
        lms.append(np.array(a))
        # lm is a list of shape=(68,2) np.array
    return lms


def align_face(filepath, lms):
    """
    :param filepath: str
    :return: PIL Image
    """

    # lms = get_landmark(filepath, dlib.shape_predictor(predictor))

    if lms is None:
        return None

    results = []
    for lm in lms:
        lm_chin = lm[0:17]  # left-right
        lm_eyebrow_left = lm[17:22]  # left-right
        lm_eyebrow_right = lm[22:27]  # left-right
        lm_nose = lm[27:31]  # top-down
        lm_nostrils = lm[31:36]  # top-down
        lm_eye_left = lm[36:42]  # left-clockwise
        lm_eye_right = lm[42:48]  # left-clockwise
        lm_mouth_outer = lm[48:60]  # left-clockwise
        lm_mouth_inner = lm[60:68]  # left-clockwise

        # Calculate auxiliary vectors.
        eye_left = np.mean(lm_eye_left, axis=0)
        eye_right = np.mean(lm_eye_right, axis=0)
        eye_avg = (eye_left + eye_right) * 0.5
        eye_to_eye = eye_right - eye_left
        mouth_left = lm_mouth_outer[0]
        mouth_right = lm_mouth_outer[6]
        mouth_avg = (mouth_left + mouth_right) * 0.5
        mouth_avg_precise = np.mean(lm_mouth_outer, axis=0)
        eye_to_mouth = mouth_avg - eye_avg

        # Choose oriented crop rectangle.
        x = eye_to_eye - np.flipud(eye_to_mouth) * [-1, 1]
        x /= np.hypot(*x)
        x *= max(np.hypot(*eye_to_eye) * 2.0, np.hypot(*eye_to_mouth) * 1.8)
        y = np.flipud(x) * [-1, 1]
        c = eye_avg + eye_to_mouth * 0.1
        quad = np.stack([c - x - y, c - x + y, c + x + y, c + x - y])
        qsize = np.hypot(*x) * 2

        quad_out = quad.copy()

        # read image
        img = PIL.Image.open(filepath)
        width = img.width

        output_size = 1024
        transform_size = 4096
        enable_padding = True

        # Shrink.
        shrink = int(np.floor(qsize / output_size * 0.5))
        if shrink > 1:
            rsize = (
                int(np.rint(float(img.size[0]) / shrink)),
                int(np.rint(float(img.size[1]) / shrink)),
            )
            img = img.resize(rsize, PIL.Image.ANTIALIAS)
            quad /= shrink
            qsize /= shrink

        # Crop.
        border = max(int(np.rint(qsize * 0.1)), 3)
        crop = (
            int(np.floor(min(quad[:, 0]))),
            int(np.floor(min(quad[:, 1]))),
            int(np.ceil(max(quad[:, 0]))),
            int(np.ceil(max(quad[:, 1]))),
        )
        crop = (
            max(crop[0] - border, 0),
            max(crop[1] - border, 0),
            min(crop[2] + border, img.size[0]),
            min(crop[3] + border, img.size[1]),
        )
        if crop[2] - crop[0] < img.size[0] or crop[3] - crop[1] < img.size[1]:
            img = img.crop(crop)
            quad -= crop[0:2]

        # Pad.
        pad = (
            int(np.floor(min(quad[:, 0]))),
            int(np.floor(min(quad[:, 1]))),
            int(np.ceil(max(quad[:, 0]))),
            int(np.ceil(max(quad[:, 1]))),
        )
        pad = (
            max(-pad[0] + border, 0),
            max(-pad[1] + border, 0),
            max(pad[2] - img.size[0] + border, 0),
            max(pad[3] - img.size[1] + border, 0),
        )
        if enable_padding and max(pad) > border - 4:
            pad = np.maximum(pad, int(np.rint(qsize * 0.3)))
            img = np.pad(
                np.float32(img), ((pad[1], pad[3]), (pad[0], pad[2]), (0, 0)), "reflect"
            )
            h, w, _ = img.shape
            y, x, _ = np.ogrid[:h, :w, :1]
            mask = np.maximum(
                1.0
                - np.minimum(np.float32(x) / pad[0], np.float32(w - 1 - x) / pad[2]),
                1.0
                - np.minimum(np.float32(y) / pad[1], np.float32(h - 1 - y) / pad[3]),
            )
            blur = qsize * 0.02
            img += (
                scipy.ndimage.gaussian_filter(img, [blur, blur, 0]) - img
            ) * np.clip(mask * 3.0 + 1.0, 0.0, 1.0)
            img += (np.median(img, axis=(0, 1)) - img) * np.clip(mask, 0.0, 1.0)
            img = PIL.Image.fromarray(np.uint8(np.clip(np.rint(img), 0, 255)), "RGB")
            quad += pad[:2]

        # Transform.
        img = img.transform(
            (transform_size, transform_size),
            PIL.Image.QUAD,
            (quad + 0.5).flatten(),
            PIL.Image.BILINEAR,
        )

        if output_size < transform_size:
            img = img.resize((output_size, output_size), PIL.Image.ANTIALIAS)

        results.append(
            {
                "image": img,
                "quad": quad_out / width,
            }
        )
    # Save aligned images.
    return results
