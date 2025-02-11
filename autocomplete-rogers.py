# Adapted to run with DeepSpeed ZeRO-3.

# Usage:
#   - Install the latest transformers & accelerate versions: `pip install -U transformers accelerate`
#   - Install deepspeed: `pip install deepspeed==0.9.5`
#   - Install TRL from main: pip install git+https://github.com/huggingface/trl.git
#   - Clone the repo: git clone github.com/huggingface/trl.git
#   - Copy this Gist into trl/examples/scripts
#   - Run from root of trl repo with: accelerate launch --config_file=examples/accelerate_configs/deepspeed_zero1.yaml examples/scripts/autocomplete-rogers.py

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
from datasets import Dataset

import torch
from accelerate import Accelerator
from peft import LoraConfig
from tqdm import tqdm
from transformers import (AutoModelForCausalLM,
                          BitsAndBytesConfig,
                          HfArgumentParser,
                          TrainingArguments,
                          AutoTokenizer)
import os
from trl import SFTTrainer

os.environ["CUDA_LAUNCH_BLOCKING"] = "1"
os.environ["TORCH_USE_CUDA_DSA"] = "1"

tqdm.pandas()


# Define and parse arguments.
@dataclass
class ScriptArguments:
    """
    The name of the Casual LM model we wish to fine with SFTTrainer
    """

    model_name: Optional[str] = field(default="HuggingFaceH4/zephyr-7b-beta", metadata={"help": "the model name"})
    dataset_name: Optional[str] = field(
        default="stingning/ultrachat", metadata={"help": "the dataset name"}
    )
    dataset_text_field: Optional[str] = field(default="text", metadata={"help": "the text field of the dataset"})
    log_with: Optional[str] = field(default="wandb", metadata={"help": "use 'wandb' to log with wandb"})
    learning_rate: Optional[float] = field(default=2.0e-5, metadata={"help": "the learning rate"})
    batch_size: Optional[int] = field(default=4, metadata={"help": "the batch size"})
    seq_length: Optional[int] = field(default=1024, metadata={"help": "Input sequence length"})
    gradient_accumulation_steps: Optional[int] = field(
        default=1, metadata={"help": "the number of gradient accumulation steps"}
    )
    load_in_8bit: Optional[bool] = field(default=False, metadata={"help": "load the model in 8 bits precision"})
    load_in_4bit: Optional[bool] = field(default=True, metadata={"help": "load the model in 4 bits precision"})
    use_peft: Optional[bool] = field(default=True, metadata={"help": "Wether to use PEFT or not to train adapters"})
    trust_remote_code: Optional[bool] = field(default=False, metadata={"help": "Enable `trust_remote_code`"})
    output_dir: Optional[str] = field(default="output", metadata={"help": "the output directory"})
    peft_lora_r: Optional[int] = field(default=16, metadata={"help": "the r parameter of the LoRA adapters"})
    peft_lora_alpha: Optional[int] = field(default=64, metadata={"help": "the alpha parameter of the LoRA adapters"})
    logging_steps: Optional[int] = field(default=100, metadata={"help": "the number of logging steps"})
    use_auth_token: Optional[bool] = field(default=False, metadata={"help": "Use HF auth token to access the model"})
    num_train_epochs: Optional[int] = field(default=-1, metadata={"help": "the number of training epochs"})
    max_steps: Optional[int] = field(default=500, metadata={"help": "the number of training steps"})
    save_steps: Optional[int] = field(
        default=100, metadata={"help": "Number of updates steps before two checkpoint saves"}
    )
    save_total_limit: Optional[int] = field(default=10, metadata={"help": "Limits total number of checkpoints."})
    push_to_hub: Optional[bool] = field(default=True, metadata={"help": "Push the model to HF Hub"})
    hub_model_id: Optional[str] = field(default="zephyr-7b-finetuned-autocomplete", metadata={"help": "The name of the model on HF Hub"})


parser = HfArgumentParser(ScriptArguments)
script_args = parser.parse_args_into_dataclasses()[0]


# Step 1: Load the Tokenizer
tokenizer = AutoTokenizer.from_pretrained(script_args.model_name)
tokenizer.add_special_tokens({'pad_token': '[PAD]'})
tokenizer.padding_side = "right"
tokenizer.add_tokens(["<AGENT_NAME>", "<PERSON>", "<URL>", "PHONE_NUMBER", "EMAIL_ADDRESS", "<CREDIT_CARD>"],
                     special_tokens=False)


# Step 2: Load the Dataset
train_df = pd.read_csv("../rogers_data/rogers_train_df.csv")
val_df = pd.read_csv("../rogers_data/rogers_val_df.csv")

trainds = Dataset.from_pandas(train_df)
valds = Dataset.from_pandas(val_df)


# Step 3: Load the model
if script_args.load_in_8bit and script_args.load_in_4bit:
    raise ValueError("You can't load the model in 8 bits and 4 bits at the same time")
elif script_args.load_in_8bit or script_args.load_in_4bit:
    quantization_config = BitsAndBytesConfig(
        load_in_8bit=script_args.load_in_8bit, load_in_4bit=script_args.load_in_4bit
    )
    # Copy the model to each device
    device_map = {"": Accelerator().local_process_index}
    torch_dtype = torch.bfloat16
else:
    device_map = None
    quantization_config = None
    torch_dtype = None

model = AutoModelForCausalLM.from_pretrained(
    script_args.model_name,
    quantization_config=quantization_config,
    device_map=device_map,
    trust_remote_code=script_args.trust_remote_code,
    torch_dtype=torch_dtype,
)

model.config.use_cache = False
model.resize_token_embeddings(len(tokenizer))


# Step 4: Define the training arguments
training_args = TrainingArguments(
    output_dir=script_args.output_dir,
    per_device_train_batch_size=script_args.batch_size,
    gradient_accumulation_steps=script_args.gradient_accumulation_steps,
    gradient_checkpointing=True,
    learning_rate=script_args.learning_rate,
    logging_steps=script_args.logging_steps,
    num_train_epochs=script_args.num_train_epochs,
    max_steps=script_args.max_steps,
    report_to=script_args.log_with,
    save_steps=script_args.save_steps,
    bf16=True,
    lr_scheduler_type="cosine",
    warmup_ratio=0.1,
    evaluation_strategy="steps",
    logging_first_step=True,

)

# Step 5: Define the LoraConfig
if script_args.use_peft:
    peft_config = LoraConfig(
        r=script_args.peft_lora_r,
        lora_alpha=script_args.peft_lora_alpha,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        bias="none",
        task_type="CAUSAL_LM",
    )
else:
    peft_config = None


# Step 6: Define the SFT Trainer
trainer = SFTTrainer(
    model=model,
    args=training_args,
    max_seq_length=script_args.seq_length,
    train_dataset=trainds,
    eval_dataset=valds,
    dataset_text_field=script_args.dataset_text_field,
    peft_config=peft_config,
    packing=False,
    neftune_noise_alpha=5,
)

trainer.train()

# Step 7: Save the model
trainer.save_model(script_args.output_dir)
