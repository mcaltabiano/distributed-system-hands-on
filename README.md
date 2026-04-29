# Sistemi Distribuiti Event-Driven

Teoria e pratica per un affondo su architetture distribuite event driven e pattern di resilienza, suggerito da Claude.

## Guida teorica e progetto pratico

---

## Indice

1. [Il Teorema CAP](#1-il-teorema-cap)
2. [PACELC — L'estensione pratica del CAP](#2-pacelc--lestensione-pratica-del-cap)
3. [Tecnologie — Zona CP](#3-tecnologie--zona-cp)
4. [Tecnologie — Zona AP](#4-tecnologie--zona-ap)
5. [Message Broker](#5-message-broker)
6. [HBase e la consistency forte (EC)](#6-hbase-e-la-consistency-forte-ec)
7. [Algoritmo Raft](#7-algoritmo-raft)
8. [Modelli di Consistency](#8-modelli-di-consistency)
9. [Progetto Pratico — E-commerce Event-Driven](#9-progetto-pratico--e-commerce-event-driven)

---

## 1. Il Teorema CAP

Il teorema (Brewer, 2000) afferma che un sistema distribuito può garantire **al massimo 2 delle 3** proprietà:

| Proprietà | Descrizione |
|---|---|
| **C — Consistency** | Ogni lettura riceve il dato più recente scritto (o un errore) |
| **A — Availability** | Ogni richiesta riceve sempre una risposta (non necessariamente aggiornata) |
| **P — Partition Tolerance** | Il sistema continua a funzionare anche se i nodi non riescono a comunicare |

> **Il punto chiave, spesso frainteso:** P non è mai davvero opzionale in un sistema distribuito reale — le partizioni di rete *accadono*. La scelta vera è quindi tra **CP** e **AP** quando si verifica una partizione.

---

## 2. PACELC — L'estensione pratica del CAP

Daniel Abadi (2012) ha esteso il CAP per coprire il 99.9% del tempo operativo: cosa succede **in assenza di partizioni**?

```
if Partition  →  scegli tra Availability e Consistency
else          →  scegli tra Latency e Consistency
```

Il CAP parla solo degli eventi rari (partizioni). PACELC aggiunge il tradeoff quotidiano: **latenza vs consistency**.

### Perché latenza e consistency sono in conflitto

In presenza di un database replicato su 3 nodi si dispone di due strade:

**Scelta EL (bassa latenza):** si scrive sul nodo locale, si risponde subito al client, si propagano i dati ai replica in background. Risposta in ~1ms, ma una lettura immediata da un altro nodo potrebbe restituire il dato vecchio.

**Scelta EC (consistency forte):** si attende che almeno 2 nodi su 3 confermino la write (quorum). Il client attende ~10-50ms in più, ma chiunque legga da qualsiasi nodo vedrà il dato aggiornato.

### Classificazione combinata PAC/ELC

| Sistema | Durante partizione | Operazione normale | Nota |
|---|---|---|---|
| Cassandra | PA (risponde sempre) | EL (write locale) | Tunable |
| DynamoDB | PA (eventual cons.) | EL o EC | Configurabile per read |
| HBase | PC (blocca) | EC (strong read) | ZooKeeper-based |
| ZooKeeper | PC (blocca) | EC | Coordinamento |
| Spanner | PC (blocca) | EC | TrueTime |

### Applicazione pratica nel progetto e-commerce

| Servizio | Scelta PACELC | Motivazione |
|---|---|---|
| Inventario | PC/EC | Non è possibile oversellare. Meglio bloccare che rispondere con dati stale |
| Carrello utente | PA/EL | Un dato stale per qualche secondo è accettabile. La latenza bassa è prioritaria |
| Notifiche email | PA/EL estremo | Una notifica in ritardo di 2s non causa alcun danno |

---

## 3. Tecnologie — Zona CP

Questi sistemi, di fronte a una partizione di rete, **rifiutano di rispondere** piuttosto che restituire dati potenzialmente stale. Il pattern comune è il **consensus algorithm** (Raft o Paxos): prima di confermare una write, la maggioranza dei nodi deve essere d'accordo.

### ZooKeeper / etcd
Casi più puri di CP. Utilizzati per coordinamento distribuito: leader election, distributed lock, configurazione condivisa. `etcd` è il cuore di Kubernetes. Non vengono impiegati come database principale, ma come "arbitri" di sistema.

### HBase
Database columnar su HDFS. La consistency è garantita da ZooKeeper internamente. Ottimo per carichi write-heavy ad alta scalabilità. Se il RegionServer perde il contatto con ZooKeeper, smette di servire richieste.

### MongoDB (default)
Configurabile. Di default è CP (`writeConcern: majority`), ma è possibile abbassare la garanzia avvicinandosi ad AP. Questo pattern si chiama **tunable consistency**.

---

## 4. Tecnologie — Zona AP

Di fronte a una partizione, questi sistemi **continuano a rispondere** accettando che alcuni nodi abbiano dati non aggiornati. Il prezzo è la **eventual consistency**: prima o poi tutti i nodi convergeranno allo stesso stato.

### Cassandra
Il caso di studio più didattico. Il livello di quorum è regolabile per ogni operazione:

```sql
CONSISTENCY ONE    -- massimamente AP
CONSISTENCY QUORUM -- compromesso (maggioranza)
CONSISTENCY ALL    -- diventa CP
```

La formula chiave: `R + W > N` per ottenere consistency (dove N = numero di repliche).

### DynamoDB
Offre due modalità di lettura esplicite:
- *Eventually consistent reads* — default, più veloci e meno costose
- *Strongly consistent reads* — costo e latenza maggiori, ma dato sempre aggiornato

### CouchDB
L'esempio estremo di AP: supporta **multi-master replication** — è possibile scrivere contemporaneamente su nodi diversi. I conflitti vengono risolti deterministicamente in un secondo momento (approccio CRDT-like).

---

## 5. Message Broker

I broker non gestiscono lo stato applicativo come i database, ma **trasportano eventi**. Il CAP si applica in modo diverso rispetto ai sistemi di storage.

| Broker | Posizione CAP | Caratteristica chiave |
|---|---|---|
| **Kafka** con `acks=all` | CP | Il producer attende conferma da tutti i replica. Zero perdita messaggi, latenza più alta |
| **RabbitMQ** | AP | Prioritizza disponibilità e throughput. Riconciliazione post-split |
| **Redis Streams** | AP / leggero | Adatto a use case a bassa latenza e volumi moderati |
| **Apache Pulsar** | CP | Separa storage (BookKeeper, CP) da compute. Alternativa moderna a Kafka |

### Criteri di scelta

Kafka con `acks=all` è la scelta indicata per sistemi finanziari o ovunque un messaggio perso costituisca un problema grave. RabbitMQ è più semplice da operare per task queue e notifiche. Redis Streams è appropriato quando Redis è già presente nell'architettura e i volumi sono moderati.

---

## 6. HBase e la consistency forte (EC)

HBase non implementa la consistency in autonomia — la **delega interamente a ZooKeeper**.

### Architettura

```
Client
  │
  ├── ZooKeeper (3-5 nodi)       ← "chi comanda?"
  │         │
  │    HMaster (1 attivo)        ← coordinamento, DDL
  │
  └── RegionServer A  B  C
            │
       [Region 1]  [Region 2]    ← ogni row key → una sola Region
```

**Il punto cruciale:** ogni riga appartiene a una e una sola Region, servita da un solo RegionServer. Non esistono repliche attive che possono divergere, eliminando il problema "quale nodo ha il dato più aggiornato".

### Percorso di una write e costo in latenza

1. **Client → ZooKeeper** (~1-2ms) — lookup del RegionServer responsabile (cachato)
2. **Client → RegionServer** (~1ms) — la write arriva al nodo responsabile
3. **Write-Ahead Log su HDFS** (~5-20ms) ← **il costo principale** — attende ACK da 2/3 DataNode
4. **MemStore in memoria** — parallelamente al WAL; le letture successive risultano molto veloci
5. **ACK al client** — emesso solo dopo la conferma della replica HDFS

```
write client
    │
    ├──► WAL → HDFS node 1 ──► ACK ┐
    │         → HDFS node 2 ──► ACK ┘  (2/3 ok) → ACK al client
    │         → HDFS node 3 ──► (non atteso)
    │
    └──► MemStore (in-memory, immediato)
```

### Latenze tipiche

| Operazione | Latenza | Causa |
|---|---|---|
| Write con WAL | 5–20ms | Attesa replica HDFS |
| Write senza WAL (`SKIP_WAL`) | <1ms | Solo MemStore, rischio perdita dati |
| Read da MemStore | 1–5ms | In memoria |
| Read da HFile | 10–50ms | Disco + HDFS |
| Read durante flush/compaction | 50–200ms | RegionServer overload |

---

## 7. Algoritmo Raft

Raft (Ongaro & Ousterhout, 2014) è stato progettato con un obiettivo esplicito: essere **comprensibile**. Risolve il problema fondamentale dei sistemi distribuiti: come fanno N nodi a mettersi d'accordo su una sequenza di valori, anche se alcuni nodi crashano o la rete si interrompe?

Raft scompone il problema in tre parti indipendenti:

1. **Leader Election** — quale nodo comanda in un dato momento
2. **Log Replication** — come il leader propaga le write agli altri
3. **Safety** — garanzie che il sistema non diverga mai

### Parte 1 — Leader Election

Ogni nodo parte come **follower** con un *election timeout* casuale (150–300ms). Se non riceve heartbeat entro il timeout, diventa **candidate**:

1. Incrementa il term corrente (es. 1→2)
2. Si auto-vota
3. Invia `RequestVote` a tutti gli altri nodi

Un nodo concede il voto se non ha ancora votato in questo term. Non appena il candidato raccoglie la **maggioranza** (quorum = ⌊N/2⌋ + 1), diventa **leader** e inizia a inviare heartbeat per affermare la propria leadership. Se il leader crasha, il primo follower a scadere avvia automaticamente una nuova elezione — il cluster si auto-guarisce senza intervento esterno.

### Parte 2 — Log Replication

```
Client → Leader
           │
           ├── aggiunge entry al proprio log (non committata)
           ├── invia AppendEntries a tutti i follower in parallelo
           │
           ├── attende ACK dalla maggioranza
           │
           ├── marca entry come committata
           └── risponde al client ✓
               (follower lenti si allineano al prossimo heartbeat)
```

Ogni entry è identificata da `(index, term)`. Il leader verifica sempre l'entry precedente prima di appendere (`prevLogIndex` + `prevLogTerm`). Se non coincidono, il follower rifiuta e il leader esegue rollback al punto di divergenza.

### Le tre garanzie di Safety

| Proprietà | Descrizione |
|---|---|
| **Election Safety** | Al massimo un leader per term |
| **Log Matching** | Se due log hanno la stessa entry allo stesso indice, sono identici su tutti gli indici precedenti |
| **Leader Completeness** | Un leader del term T contiene tutte le entry committate nei term precedenti |

### Raft vs Paxos

Paxos è più generale (consensus su singoli valori) ma non specifica come costruire un log replicato completo — ogni implementazione riempie i buchi in modo differente. Raft è invece progettato esplicitamente per un log replicato, con leader election, membership changes e snapshot tutti definiti nel paper originale.

**Usano Raft:** etcd, CockroachDB, TiKV, Consul.
**Usano Paxos:** Google Chubby, Spanner (sviluppati prima di Raft).

---

## 8. Modelli di Consistency

I modelli di consistency rappresentano lo strato che il codice applicativo tocca direttamente. Non descrivono *come* i nodi si sincronizzano (questo è compito di Raft, WAL, quorum) — descrivono **cosa vede il client** dopo una write.

La domanda centrale è sempre la stessa: se si scrive un valore sul nodo A, quando lo vede il client che legge dal nodo B?

### Spettro dal più forte al più debole

#### Linearizability (Strong Consistency)
Ogni operazione appare istantanea e atomica. Il sistema si comporta come un singolo nodo. Una read restituisce **sempre** la write più recente, globalmente.

```
Client A:  write x=10 → ok
Client B:  legge da qualsiasi nodo → x=10 ✓ (immediatamente)
```

**Costo:** alta latenza, bassa disponibilità in caso di partizione.
**Esempi:** etcd, ZooKeeper, Spanner, CockroachDB.
**Casi d'uso:** leader election, distributed lock, sequencer di ID.

---

#### Sequential Consistency
Tutte le operazioni appaiono in un ordine globale consistente, ma quell'ordine non deve necessariamente corrispondere al tempo reale. Client diversi vedono lo stesso ordine, pur potendo non essere aggiornati al momento presente.

```
Client A:  write x=10 → write x=20
Client B:  read x=10 → read x=20  (mai 20 → 10) ✓
```

**Esempi:** ZooKeeper per operazioni di watch. Modello prevalentemente teorico.

---

#### Causal Consistency
Se l'operazione B dipende causalmente da A, tutti i nodi vedono A prima di B. Operazioni non correlate possono apparire in ordini diversi.

```
Client A:  post="Ciao" → reply="Rispondo al tuo ciao"
Client B:  vede il post, poi la reply — mai al contrario ✓
```

**Costo:** implementazione complessa (vector clock o simili).
**Esempi:** MongoDB causal sessions, alcune configurazioni Cassandra.
**Casi d'uso:** social feed, commenti, chat.

---

#### Read-Your-Writes
Dopo una write, lo stesso client vede sempre il valore aggiornato nelle letture successive. Altri client possono ancora vedere il valore vecchio. Garanzia **per sessione**, non globale.

```
Client A:  write bio="Dev" → read bio="Dev" ✓
Client B:  read bio=""  (stale accettabile per altri client)
```

**Esempi:** DynamoDB con sticky sessions, PostgreSQL read replicas con routing.
**Casi d'uso:** profilo utente, impostazioni, "aggiorna e rileggi subito".

---

#### Monotonic Reads
Un client non vedrà mai un valore più vecchio di quello già letto. Una volta osservato x=10, il sistema non restituirà mai più x=5 — anche leggendo da repliche diverse.

```
Client A:  read x=10 → read x=10 → read x=20 ✓
Senza garanzia: read x=10 → read x=5 ✗ (possibile con load balancer)
```

**Esempi:** Cassandra con timestamp tracking, sistemi con vector clock lato client.

---

#### Eventual Consistency
Se le write si interrompono, tutti i nodi convergeranno eventualmente allo stesso valore. Non esiste garanzia su *quando* avvenga la convergenza né su cosa sia visibile nel frattempo. È la promessa minima che un sistema distribuito AP può offrire.

```
Client A:  write x=10
Client B:  read x=0 → read x=0 → ... → read x=10 ✓ (prima o poi)
```

**Costo:** anomalie visibili al client, richiede idempotenza nei consumer.
**Esempi:** Cassandra (ONE), DynamoDB (eventually consistent reads), DNS, CDN.
**Casi d'uso:** contatori like/view, notifiche, cache, ricerche non critiche.

> **Il tranello più comune:** eventual consistency non significa "dati sbagliati". Significa che esiste una *finestra di inconsistency* che si chiude nel tempo — tipicamente millisecondi o secondi nei sistemi moderni. Il problema emerge quando il codice assume linearizability su un sistema che garantisce solo eventual.

### Come si combinano nella pratica

I modelli non si escludono — si **impilano per operazione**. In un e-commerce è comune trovare modelli diversi all'interno dello stesso sistema:

| Operazione | Modello | Motivazione |
|---|---|---|
| Sottrazione inventario | Linearizability | Non è possibile oversellare |
| Aggiornamento profilo utente | Read-your-writes | L'utente si aspetta di vedere subito le proprie modifiche |
| Contatore visualizzazioni prodotto | Eventual | Un dato leggermente stale è accettabile |
| Thread commenti | Causal | La risposta deve comparire dopo il post originale |

---

## 9. Progetto Pratico — E-commerce Event-Driven

### Obiettivo didattico

Il progetto non mira a costruire un e-commerce di produzione, ma a realizzare un **laboratorio** in cui è possibile:
- Osservare il comportamento del sistema durante una partizione di rete simulata
- Confrontare concretamente una write CP e una AP
- Sperimentare eventual consistency e idempotenza
- Implementare il Saga pattern e comprenderne la necessità

### Architettura

```
                        Client HTTP
                             │
                      Order Service
                   (CP · Outbox pattern)
                      PostgreSQL
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
    ┌───────────────────────────────────────────────────┐
    │                      Kafka                        │
    │  topics: order.placed · payment.processed         │
    │          inventory.reserved · notification.send   │
    └─────────────┬─────────────┬─────────────┬─────────┘
                  │             │             │
          Inventory         Payment      Notification
           Service           Service       Service
         (CP · FOR UPDATE) (CP · idem.)   (AP · Redis)
         PostgreSQL         PostgreSQL     Redis
```

**Saga (choreography)** — pattern che collega i tre servizi tramite eventi compensativi in caso di fallimento.

**Network partition simulator** — `docker network disconnect` per osservare il comportamento CP vs AP in tempo reale.

### Concetti appresi per ogni componente

**Order Service + Outbox pattern**
Non è corretto eseguire `BEGIN TRANSACTION; insert order; send kafka message; COMMIT`: il message broker non partecipa alla transazione DB. L'Outbox risolve il problema scrivendo l'evento in una tabella nella *stessa transazione* del DB; un relay asincrono si occupa poi della pubblicazione su Kafka.

**Inventory Service con `SELECT FOR UPDATE`**
Il lock pessimistico garantisce che due ordini concorrenti non sottraggano lo stesso stock. È la ragione per cui il servizio è CP — linearizability applicata in concreto.

**Payment Service con idempotency key**
In un sistema AP/eventual i messaggi possono arrivare *due volte* (at-least-once delivery di Kafka). Senza idempotenza il cliente verrebbe addebitato due volte. Con l'idempotency key, la seconda esecuzione è un no-op.

**Notification Service AP**
Un'email duplicata è fastidiosa, non catastrofica. Progettare il servizio come AP elimina complessità superflua — prima dimostrazione pratica che non tutto richiede CP.

**Saga choreography**
In assenza di transazioni distribuite (il protocollo 2PC non viene utilizzato in produzione), i fallimenti si gestiscono con eventi compensativi. Se il pagamento fallisce, viene pubblicato `payment.failed` e l'inventory service rilascia lo stock riservato.

**Partition simulator**
Il concetto di partizione di rete si comprende appieno non leggendone la definizione, ma *osservando* cosa accade quando un container viene disconnesso dalla rete.

### Struttura del repository

```
ecommerce-distributed/
├── docker-compose.yml              ← Kafka, Zookeeper, PostgreSQL x2, Redis
├── services/
│   ├── order-service/              ← Python/FastAPI
│   │   ├── main.py
│   │   ├── outbox_relay.py         ← legge outbox table e pubblica su Kafka
│   │   └── models.py
│   ├── inventory-service/          ← Python/FastAPI
│   │   ├── main.py
│   │   └── consumer.py             ← ascolta order.placed
│   ├── payment-service/            ← Python/FastAPI
│   │   ├── main.py
│   │   └── consumer.py             ← idempotency key logic
│   └── notification-service/       ← Python/FastAPI
│       ├── main.py
│       └── consumer.py             ← eventual, AP, Redis
├── scripts/
│   ├── simulate_partition.sh       ← docker network disconnect/connect
│   └── load_test.py                ← ordini concorrenti per osservare CP vs AP
└── docs/
    └── observations.md             ← diario degli esperimenti
```

### Piano di sviluppo in 4 fasi

| Fase | Componenti | Concetti toccati |
|---|---|---|
| **1** | Docker Compose + Kafka funzionante | Setup base, topic, producer/consumer |
| **2** | Order + Inventory con Outbox | CP, transazioni, at-least-once delivery |
| **3** | Payment con idempotency + Saga | Eventual consistency, eventi compensativi |
| **4** | Partition simulator + osservazioni | CAP in pratica, PACELC vissuto |

### Esperimenti da eseguire nella Fase 4

```bash
# Simula una partizione sul servizio inventario
docker network disconnect ecommerce-net inventory-service

# Lancia 100 ordini concorrenti
python scripts/load_test.py --orders 100 --product-id abc --stock 50

# Osservazioni attese:
# - Order service: risponde sempre (AP) o blocca (CP)?
# - Inventory service: quanti oversell si verificano?
# - Cosa accade quando il nodo viene riconnesso?
docker network connect ecommerce-net inventory-service
```

```bash
# Simula la morte del leader Kafka
docker stop kafka-broker-1

# Osservazioni attese:
# - Quanto tempo impiega il cluster a eleggere un nuovo leader?
# - Cosa riceve il producer durante il failover?
# - Gli ordini in volo vengono persi o ritrasmessi?
```

### Letture consigliate

| Risorsa | Motivo |
|---|---|
| *Designing Data-Intensive Applications* — Kleppmann | Il riferimento assoluto sull'argomento. Capitoli 5, 7 e 9 sono i più rilevanti |
| *Building Event-Driven Microservices* — Bellemare | Direttamente applicabile al progetto |
| Paper originale Raft — Ongaro & Ousterhout (2014) | Denso ma accessibile; consigliata la lettura integrale |
| "CAP Twelve Years Later" — Brewer (2012) | Revisione critica del teorema da parte del suo autore |
| Blog di Martin Fowler su Event Sourcing e CQRS | Pattern che estendono naturalmente il progetto |

---

*Roadmap: CAP → PACELC → Tecnologie → HBase/EC → Raft → Modelli di Consistency → Progetto pratico*