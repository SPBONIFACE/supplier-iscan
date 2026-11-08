"""The public demo (#50): pre-built, read-only profiles that anyone can browse without an account.

- `build.py`: copies finished runs of the configured demo organisation into `DemoProfile` records,
  names stripped (the administrator command, `python -m app.demo`);
- `routes.py`: the read-only public endpoints, which read `DemoProfile` and nothing else;
- `readonly.py`: every request under `/demo` other than GET is refused with 403.

Nothing in this package calls a model, queues a job, crawls or writes in a request.
"""
