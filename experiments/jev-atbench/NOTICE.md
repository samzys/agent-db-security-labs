# Attribution and reuse boundaries

## Original software

The original scoring implementation and accompanying explanations in this
directory use the repository's [MIT license](../../LICENSE). No third-party
model weights or inference implementation are included.

## ATBench annotations

Numeric case IDs and benchmark labels are derived from
[AI45Research/ATBench](https://huggingface.co/datasets/AI45Research/ATBench),
revision `4476ef92ed8f85c8d58d8a5b9dfdf55aa7893138`.
The official data card identifies both configurations as **Apache-2.0**.
The upstream project is [AgentDoG](https://github.com/AI45Lab/AgentDoG);
see the [paper](https://arxiv.org/abs/2601.18491).

The derived records omit all trajectory and tool text, retaining only IDs,
labels, source-message hashes, recorded numeric model outputs, and status.
They are modified evaluation records, not verbatim copies of the upstream dataset.
The Apache license for upstream-derived annotations is included at
[`data/LICENSE-ATBENCH.txt`](data/LICENSE-ATBENCH.txt). The repository's MIT
license does not replace upstream attribution or license obligations.

## Recorded model outputs

Jev and AgentDoG names identify evaluated systems, not sponsorship or endorsement.
Numerical outputs are supplied for auditing and replaying this reported evaluation.
No rights to a provider's service, documentation, model weights, or other technology
are granted by this package.

[TypeSafe's public service agreement](https://typesafe.ai/legal/mca) addresses
output ownership and restricts certain uses, including distillation and imitation
training. Sharing these evaluation artifacts does not authorise those activities
or override a user's applicable service terms. This project is not a training dataset.
No claim is made that TypeSafe reviewed or approved these results.

References to public documentation are links, not copies of provider documentation.
No account credentials, provider billing information, private orders, or raw response
envelopes are included. This notice is not legal advice or a review of every account's terms.
