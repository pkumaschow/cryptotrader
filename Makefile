IMAGE   := pkumaschow/cryptotrader
TAG     := latest
ENVFILE := .env
CTR     := docker

build:
	$(CTR) build -t $(IMAGE):$(TAG) .

run:
	$(CTR) run --rm \
	  --env-file $(ENVFILE) \
	  -v $(PWD)/cryptotrader.db:/app/cryptotrader.db \
	  $(IMAGE):$(TAG)

tui:
	$(CTR) run --rm -it \
	  --env-file $(ENVFILE) \
	  -v $(PWD)/cryptotrader.db:/app/cryptotrader.db \
	  $(IMAGE):$(TAG) --tui

push:
	$(CTR) push $(IMAGE):$(TAG)

shell:
	$(CTR) run --rm -it \
	  --env-file $(ENVFILE) \
	  -v $(PWD)/cryptotrader.db:/app/cryptotrader.db \
	  --entrypoint bash \
	  $(IMAGE):$(TAG)

.PHONY: build run tui push shell
