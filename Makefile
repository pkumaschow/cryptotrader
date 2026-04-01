IMAGE   := pkumaschow/cryptotrader
TAG     := latest
ENVFILE := .env

build:
	docker build -t $(IMAGE):$(TAG) .

run:
	docker run --rm \
	  --env-file $(ENVFILE) \
	  -v $(PWD)/cryptotrader.db:/app/cryptotrader.db \
	  $(IMAGE):$(TAG)

tui:
	docker run --rm -it \
	  --env-file $(ENVFILE) \
	  -v $(PWD)/cryptotrader.db:/app/cryptotrader.db \
	  $(IMAGE):$(TAG) --tui

push:
	docker push $(IMAGE):$(TAG)

shell:
	docker run --rm -it \
	  --env-file $(ENVFILE) \
	  -v $(PWD)/cryptotrader.db:/app/cryptotrader.db \
	  --entrypoint bash \
	  $(IMAGE):$(TAG)

.PHONY: build run tui push shell
