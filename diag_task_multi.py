import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trl.util import load_config, count_tokens
from trl import Engine
from bench.providers import get_provider
from bench.realistic_tasks import make_realistic_suite

cfg = load_config('config.yaml')
cfg.setdefault('local_model',{})
cfg['local_model']['provider']='ollama'; cfg['local_model']['model']='llama3.2:3b'
model = get_provider('mock', cfg)
engine = Engine(cfg)

NF, NU = 5, 2
suite = make_realistic_suite(n_favorable=NF, n_unfavorable=NU, seed=7,
                             min_amounts=3, max_amounts=4)
b_ok=t_ok=0; b_tok=0; t_tok=0; fav_b=0; fav_t=0
print(f"Running {len(suite)} tasks with REAL llama3.2:3b compression...", flush=True)
for i,task in enumerate(suite):
    msgs=task.messages
    t=time.time()
    b=model.call(msgs, task, 0, True)
    res=engine.process(msgs)
    tt=model.call(res.messages, task, 0, True)
    bi=sum(count_tokens(m.content) for m in msgs)
    ti=sum(count_tokens(m.content) for m in res.messages)
    b_ok+=b.success; t_ok+=tt.success; b_tok+=bi; t_tok+=ti
    if task.profile=='favorable': fav_b+=bi; fav_t+=ti
    print(f"  [{i+1}/{len(suite)}] {task.profile:11s} {time.time()-t:4.1f}s  "
          f"tok {bi}->{ti}  baseline_ok={b.success} llama_ok={tt.success}", flush=True)

n=len(suite)
print("\n===== REAL llama3.2:3b RESULT =====", flush=True)
print(f"quality: baseline {100*b_ok/n:.0f}% -> llama-compressed {100*t_ok/n:.0f}%  "
      f"({'PASS: facts preserved' if t_ok>=b_ok else 'FAIL: llama dropped facts'})")
print(f"tokens (all):       {b_tok} -> {t_tok}  ({100*(1-t_tok/b_tok):.1f}% less)")
if fav_b: print(f"tokens (favorable): {fav_b} -> {fav_t}  ({100*(1-fav_t/fav_b):.1f}% less)")
print("DONE")
