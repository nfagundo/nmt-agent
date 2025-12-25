from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

model_name = "Helsinki-NLP/opus-mt-en-es"

tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSeq2SeqLM.from_pretrained(model_name)

text = "Hello, how are you?"

inputs = tokenizer(text, return_tensors="pt", truncation=True)
outputs = model.generate(**inputs, max_new_tokens=80)
translated = tokenizer.decode(outputs[0], skip_special_tokens=True)

print(translated)
