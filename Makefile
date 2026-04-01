IMAGE   := pkumaschow/cryptotrader
TAG     := latest
ENVFILE := .env
CTR     := docker

build:
	$(CTR) build -t $(IMAGE):$(TAG) .

run:
	touch $(PWD)/cryptotrader.db && chmod 666 $(PWD)/cryptotrader.db
	$(CTR) run --rm \
	  --env-file $(ENVFILE) \
	  -v $(PWD)/cryptotrader.db:/app/cryptotrader.db \
	  $(IMAGE):$(TAG)

tui:
	touch $(PWD)/cryptotrader.db && chmod 666 $(PWD)/cryptotrader.db
	$(CTR) run --rm -it \
	  --env-file $(ENVFILE) \
	  -v $(PWD)/cryptotrader.db:/app/cryptotrader.db \
	  $(IMAGE):$(TAG) --tui

push:
	$(CTR) push $(IMAGE):$(TAG)

shell:
	touch $(PWD)/cryptotrader.db && chmod 666 $(PWD)/cryptotrader.db
	$(CTR) run --rm -it \
	  --env-file $(ENVFILE) \
	  -v $(PWD)/cryptotrader.db:/app/cryptotrader.db \
	  --entrypoint bash \
	  $(IMAGE):$(TAG)

.PHONY: build run tui push shell
