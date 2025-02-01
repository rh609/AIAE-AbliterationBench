import os
import argparse
import sys
import platform
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from erisforge.eris_forge import Forge
from erisforge.scorers.refusal_scorer.expression_refusal_scorer import ExpressionRefusalScorer
import matplotlib.pyplot as plt
import numpy as np
from datasets import load_dataset
from sklearn.model_selection import train_test_split

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def parse_arguments():
    parser = argparse.ArgumentParser(description='Run abliteration benchmark')
    parser.add_argument('-n', '--model_names', default=['Qwen/Qwen-1.5-0.5B-Chat','google/gemma-1.1-2b-it'], type=list[str], help='Model name')
    parser.add_argument('-m', '--max_inst', default=20, type=int, help='Number of instructions to process')
    parser.add_argument('-l', '--num_layers', default=2, type=int, help='Difference between max_layer and min_layer')
    parser.add_argument('-b', '--batch_size', default=10, type=int, help='Instructions processed per batch - increase based on memory available')
    return parser.parse_args()

args = parse_arguments()

# Download datasets:
def get_harmful_instructions():
    hf_path = 'Undi95/orthogonal-activation-steering-TOXIC'
    dataset = load_dataset(hf_path)
    instructions = [i['goal'] for i in dataset['test']]
    train, test = train_test_split(instructions, test_size=0.2, random_state=42)
    return train, test

def get_harmless_instructions():
    hf_path = 'tatsu-lab/alpaca'
    dataset = load_dataset(hf_path)
    # filter for instructions that do not have inputs
    instructions = []
    for i in range(len(dataset['train'])):
        if dataset['train'][i]['input'].strip() == '':
            instructions.append(dataset['train'][i]['instruction'])
    train, test = train_test_split(instructions, test_size=0.2, random_state=42)
    return train, test

dataset = [get_harmful_instructions(), get_harmless_instructions()] # Format: [harmful, harmless]

refusal_scores_baseline = []
refusal_scores_intervention = []
model_names = args.model_names
for model_name in model_names:
    print(f"\n\n\n##################\n\n\nRunning ablation benchmark for model: {model_name}\n\n\n##################\n\n\n")
    # Initialize erisforge object:
    forge = Forge()

    # Load model and tokenizer:
    # model_name = args.model_name
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,  
    ).to(forge.device)  
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)

    # Assess refusal score on base model:
    max_inst = args.max_inst
    batch_size = args.batch_size
    conversations_standard = []
    for batch in range(0, len(dataset[0][1][:max_inst]), batch_size):
        conversations_standard.extend(forge.evaluate_base_model(
        model=model,
        tokenizer=tokenizer,
        max_new_tokens=50,
        instructions=dataset[0][1][:max_inst][batch:min(batch + batch_size, len(dataset[0][1][:max_inst]))]
        )
    )

    # Initialize scorer object:
    scorer = ExpressionRefusalScorer()

    # Calculate refusal score for base model:
    refusal_scores = []
    for conv in conversations_standard:
        refusal_scores.append( scorer.score(user_query=conv[0]["content"], model_response=conv[1]["content"]) )
        # print(f'\nUser query:\n{conv[0]["content"]}\n')
        # print(f'Model response:\n{conv[1]["content"]}')
    refusal_score_base = sum(refusal_scores)/len(refusal_scores)
    print(f'''\nModel before ablation has {refusal_score_base:.2f} refusal score - {sum(refusal_scores):.0f} harmful prompts refused over {len(refusal_scores)} prompts.\n''')

    # Select layers:
    tot_number_of_layers = len(model.model.layers)
    min_layer = int( (tot_number_of_layers / 2) - (args.num_layers / 2) )
    max_layer = int( min_layer + args.num_layers )

    # Find direction through layer search and run ablation:
    result_dict = forge.find_approximate_best_objective_behaviour_direction(
        model=model,
        tokenizer=tokenizer,
        scorer=scorer,
        eval_objective_behaviour_instructions=dataset[0][1][:max_inst],
        eval_antiobjective_instructions=dataset[1][1][:max_inst],
        min_layer=min_layer,
        max_layer=max_layer,
    )

    # Get the lowest refusal score after ablation (dict is sorted in an ascending order by score):
    final_refusal_score = result_dict[0]['score'] 

    refusal_scores_baseline.append(refusal_score_base)
    refusal_scores_intervention.append(final_refusal_score)
    # Print results:
    print("\nRefusal score before ablation: ", refusal_score_base)
    print("Refusal score after ablation: ", final_refusal_score)
    print("Refusal Drop Rate: ", refusal_score_base - final_refusal_score)

from barplot import plot_refusal_scores 
plot_refusal_scores(model_names, refusal_scores_baseline, refusal_scores_intervention)



