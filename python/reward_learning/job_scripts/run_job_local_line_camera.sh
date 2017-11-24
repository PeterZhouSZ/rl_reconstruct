#!/bin/bash

if [ -z $1 ]; then
    echo "Job id needs to be provided"
    exit 1
fi

JOB_ID=`printf "%04d" $1`

export CUDA_VISIBLE_DEVICES=$2

export LD_LIBRARY_PATH=/usr/local/cuda/extras/CUPTI/lib64:$LD_LIBRARY_PATH

export RLRECONSTRUCT_PY_DIR=$HOME/rl_reconstruct/python


DATA_BASE_PATH=$HOME/reward_learning/datasets/line_camera/
export DATA_PATH=$DATA_BASE_PATH/in_out_grid_16x16x16_0-1-2-3-4_HorizontalEnvironment_CustomScenes_buildings_greedy_train.lmdb
export TEST_DATA_PATH=$DATA_BASE_PATH/in_out_grid_16x16x16_0-1-2-3-4_HorizontalEnvironment_CustomScenes_buildings_greedy_test.lmdb
export DATA_TYPE=lmdb
#DATA_BASE_PATH=$HOME/reward_learning/datasets/line_camera/in_out_grid_16x16x16_0-1-2-3-4_HorizontalEnvironment_CustomScenes_buildings_greedy/
#export DATA_PATH=$DATA_BASE_PATH/train_reward_prediction.lmdb
#export TEST_DATA_PATH=$DATA_BASE_PATH/test_reward_prediction.lmdb
export DATA_TYPE=lmdb
export MODEL_PATH=$HOME/reward_learning/models/reward_prediction/$JOB_ID
export LOG_PATH=$HOME/reward_learning/logs/reward_prediction/$JOB_ID

mkdir -p $LOG_PATH
mkdir -p $MODEL_PATH

bash run_job_${JOB_ID}.sh ${@:3} 2>&1 | tee $LOG_PATH/stdout.log

