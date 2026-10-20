# Azurite

The Azure Blob Storage emulator from Microsoft: a local object store that speaks the Azure Blob API. Gravitee's storage resource (`gravitee-resource-storage-azure-blob`) connects to it, so policies that offload content, such as Kafka Offloading, run on this machine with no cloud account.

It exists because the Kafka Offloading policy stores content in Azure Blob Storage only. S3 and MinIO are not supported by the policy.

## Use it

Inside Docker, the Blob service is `http://azurite:10000/devstoreaccount1`. The emulator has one well-known account, `devstoreaccount1`, with a public key that Microsoft documents. A storage resource connects with this connection string:

```text
DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://azurite:10000/devstoreaccount1;
```

The container (blob folder) must exist before a resource writes to it. A playground creates its own.

## Settings

| Setting | Meaning |
|---|---|
| `AZURITE_VERSION` | Azurite version (image tag) |

## What stays after removal

The blobs live in the Docker volume `data-azurite`. Stopping the add-on keeps them, and `make reset` deletes them.
