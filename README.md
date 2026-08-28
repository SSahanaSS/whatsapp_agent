# 🤖 Agentic WhatsApp Automation for Small-Scale Businesses

An **AI-powered Agentic WhatsApp Automation platform** designed to help small-scale businesses automate customer interactions, order management, FAQs, complaints, payments, and business operations directly through WhatsApp.

The project demonstrates the system using a **home-based food business as the primary domain**, where customers can interact with an AI agent to browse the menu, place orders, make payments, track deliveries, and resolve issues.

---

## 🏗️ Architecture

```text
                         Customer
                            │
                            ▼
                    📱 WhatsApp
                            │
                            ▼
                  ┌───────────────────┐
                  │   FastAPI Webhook │
                  └─────────┬─────────┘
                            │
                            ▼
                   LangGraph Supervisor
                      Intent Routing
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
        Order Agent     FAQ Agent    Complaint Agent
              │             │             │
              ▼             ▼             ▼
          Ordering         RAG          Resolution
          Cart/Menu       Search        & Escalation
          Payments        FAQ KB
              │             │             │
              └─────────────┼─────────────┘
                            │
                            ▼
                   Business Services
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
        PostgreSQL       Razorpay       ETA Service
             │              │              │
             └──────────────┼──────────────┘
                            │
                            ▼
                    WhatsApp Response
```

---

## 🎯 Objective

Small-scale businesses often depend heavily on manual WhatsApp communication for:

* Customer queries
* Taking orders
* Sharing product information
* Handling complaints
* Payment follow-ups
* Delivery updates

This project aims to automate these repetitive operations using **agentis while keeping the business owner in control of the overall workflow**.

The architecture is domain-independent and can be adapted to different small businesses. A **home food business** is used as the primary implementation and demonstration domain.

---

## ✨ Key Features

* 🤖 Agentic WhatsApp customer interaction
* Intelligent intent detection and routing
* Automated order management
* Menu and product information retrieval
* RAG-based FAQ answering
* Complaint and refund handling
* Payment-link generation
* Delivery ETA calculation
* Customer conversation state and history
* Location-aware ordering
* Multilingual interaction
* Business operations dashboard
* PostgreSQL data persistence
* Human escalation for complex issues

---

## 🧠 Agentic Architecture

Instead of using a single chatbot, the system uses **multiple specialized AI agents** coordinated through **LangGraph**.

```text
                     Supervisor
                         │
          ┌──────────────┼──────────────┐
          │              │              │
          ▼              ▼              ▼
      Order Agent    FAQ Agent    Complaint Agent
          │              │              │
          ▼              ▼              ▼
       Business       Knowledge       Issue
       Operations      Retrieval      Resolution
```

The **Supervisor Agent** determines the customer's intent and routes the conversation to the appropriate specialized agent.

For example:

```text
"Can I order 2 biryanis?"
          ↓
        ORDER
          ↓
     Order Agent
```

```text
"Do you deliver to my area?"
          ↓
         FAQ
          ↓
      FAQ Agent
```

```text
"My order arrived damaged."
          ↓
      COMPLAINT
          ↓
   Complaint Agent
```

---

## 🛒 Order Automation

For the home food business use case, the Order Agent can manage the complete ordering workflow.

```text
Customer
   ↓
Browse Menu
   ↓
Select Items
   ↓
Manage Cart
   ↓
Collect Customer Details
   ↓
Collect Delivery Location
   ↓
Confirm Order
   ↓
Generate Payment Link
   ↓
Payment
   ↓
Order Confirmation
```

The agent can perform business operations through tools instead of simply generating conversational responses.

---

## 📚 RAG-Based FAQ System

The FAQ Agent uses **Retrieval-Augmented Generation (RAG)** to answer questions using the business's own knowledge base.

For the home food business, the knowledge base can contain information such as:

* Menu information
* Delivery areas
* Operating hours
* Payment methods
* Ingredients
* Food-related policies
* Cancellation and refund policies

### RAG Workflow

```text
Customer Question
       ↓
    FAQ Agent
       ↓
Hybrid Retrieval
       ↓
Relevant FAQ Results
       ↓
Confidence Check
       ↓
LLM Response
       ↓
Customer
```

The system uses **semantic and keyword-based retrieval** with vector embeddings stored using PostgreSQL/pgvector.

---

## 📢 Complaint Automation

The Complaint Agent handles customer issues and determines the appropriate resolution.

Possible workflows include:

```text
Customer Complaint
        ↓
Identify Issue
        ↓
┌───────┼───────────┐
▼       ▼           ▼
Refund  Replacement Escalation
        │
        ▼
    Resolution
```

This reduces the need for manual handling of repetitive customer-support requests while allowing complex cases to be escalated.

---

## 💳 Payment Automation

The system integrates payment functionality using **Razorpay**.

The ordering workflow can progress from:

```text
Order → Payment Link → Payment → Confirmation
```

Payment information can then be associated with the corresponding order in the database.

---

## 📍 Location & Delivery

Customers can share their WhatsApp location while placing an order.

The system can use the location information to support:

* Delivery-area validation
* Customer address handling
* Delivery estimation
* ETA calculation

The project includes a dedicated ETA service for calculating delivery estimates.

---

## 📊 Business Operations Dashboard

The platform also provides an operations dashboard for the business owner.

The dashboard can provide information such as:

* Today's orders
* Revenue
* Payment status
* Active orders
* Refunds
* Hourly order statistics
* Customer complaints
* Escalated issues
* Menu availability

This allows the business owner to monitor automated operations without manually reviewing every WhatsApp conversation.

---

## 🗄️ Data Layer

The system uses **PostgreSQL** for persistent storage.

The database manages information such as:

* Customers
* Orders
* Order status
* Payment status
* Menu items
* Conversations
* Complaints
* Support tickets
* FAQ embeddings

**pgvector** is used to support vector-based FAQ retrieval.

---

## 📱 WhatsApp Integration

WhatsApp acts as the primary customer interaction channel.

```text
Customer
   ↓
WhatsApp
   ↓
Webhook
   ↓
AI Agent System
   ↓
Business Operations
   ↓
WhatsApp Response
```

Customers do not need to install a separate application, making the system particularly suitable for small businesses that already use WhatsApp for customer communication.

---

## 🔄 End-to-End Workflow

```text
                         Customer
                            │
                            ▼
                       WhatsApp
                            │
                            ▼
                     FastAPI Webhook
                            │
                            ▼
                  LangGraph Supervisor
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
         Order Agent     FAQ Agent    Complaint Agent
             │              │              │
             ▼              ▼              ▼
        Cart / Order       RAG          Refund /
        Payment            Search       Escalation
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                    Business Services
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
         PostgreSQL      Razorpay      ETA Service
                            │
                            ▼
                      WhatsApp Reply
```

---

## 🧩 Project Structure

```text
whatsapp_agent/
│
├── agents/
│   ├── supervisor.py       # Intent routing agent
│   ├── oagent.py           # Order management agent
│   ├── faq.py              # RAG-based FAQ agent
│   └── complaint.py        # Complaint handling agent
│
├── models/
│   └── state.py            # Shared agent state
│
├── services/
│   ├── db.py               # Database operations
│   ├── dbservice.py        # Business database services
│   ├── eta.py              # Delivery ETA
│   ├── faqtools.py         # FAQ retrieval
│   ├── gemini.py           # Gemini integration
│   └── wa.py               # WhatsApp integration
│
├── frontend/
│   └── vite-project/       # Operations dashboard frontend
│
├── graph.py                # LangGraph workflow
├── main.py                 # FastAPI + WhatsApp webhook
├── dashboard_api.py        # Dashboard API
├── setupfaq.py             # FAQ knowledge-base setup
└── faq.pdf                 # Business FAQ knowledge base
```

---

## 🛠️ Technology Stack

### AI & Agentic Systems

* Python
* LangGraph
* LLM-based intent classification
* Groq
* Llama models
* Google Gemini
* Retrieval-Augmented Generation (RAG)
* RAGAS

### Backend

* FastAPI
* PostgreSQL
* pgvector

### Frontend

* React
* Vite

### Integrations

* WhatsApp
* Razorpay
* Google Embeddings
* Neon PostgreSQL

---

## 🌐 Domain Applicability

Although the project is demonstrated using a **home food business**, the underlying agentic architecture can be adapted to other small-scale businesses.

```text
             Agentic WhatsApp Platform
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
    Home Food       Boutique       Local Services
     Business        Store            Business
        │              │              │
        └──────────────┼──────────────┘
                       ▼
               Specialized Agents
```

The same architecture can be adapted for businesses such as:

* Home food businesses
* Small retail stores
* Boutiques
* Bakeries
* Local service providers
* Home-based businesses

Only the **business knowledge base, tools, workflows, and domain-specific logic** need to be modified.

---

## 🎯 Project Highlights

* Multi-agent AI architecture using LangGraph
* Automated WhatsApp-based customer interaction
* LLM-powered intent routing
* Tool-driven business operations
* RAG-based knowledge retrieval
* Automated order and complaint workflows
* Payment integration
* PostgreSQL + pgvector
* Delivery ETA calculation
* Operations dashboard
* Designed with small-scale businesses in mind

---

## 👩‍💻 Project Overview

**Topic:** Agentic WhatsApp Automation for Small-Scale Businesses

**Primary Domain:** Home Food Business

**Core Concept:** Use a multi-agent AI system to automate repetitive customer-facing and operational tasks through WhatsApp while providing a scalable architecture that can be adapted to other small businesses.
