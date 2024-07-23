# Large language Model Fine tuning and Inference Scripts

## Description
This repository includes all scripts to plugin any open source LLM model and finetune it for custom downstream tasks.
1. It uses Deep Speed based ZERO-Infinity Optimizations to fit models greater than GPU memory by offloading Gradients, Optimizers onto CPU memory and NVMe (SSD)
2. Accelerate library to distribute the workloads onto multiple GPUs in a node
3. PEFT LORA Adapters, merging them with pretrained base LLM models
4. vLLM Inference Server which can handle continuous batching and produce 23x higher throughput than naive pipelines

## Visuals
Depending on what you are making, it can be a good idea to include screenshots or even a video (you'll frequently see GIFs rather than actual videos). Tools like ttygif can help, but check out Asciinema for a more sophisticated method.

## Installation
Required packages to run these scripts are documented within the scripts

## Authors and acknowledgment
1) Shreyas S K (shreyas.sk@khoros.com)
