import inspect
import lerobot.policies.factory as factory

print("Fonctions disponibles :")
print([
    name for name in dir(factory)
    if "processor" in name.lower()
])

if hasattr(factory, "make_pre_post_processors"):
    print(
        "Signature :",
        inspect.signature(factory.make_pre_post_processors)
    )