# AutoDialer EC2 pilot

The private pilot runs on one Ubuntu 24.04 x64 EC2 instance in US East (N. Virginia). Use the Tailscale Android app for connectivity and Chrome for AutoDialer. The server accepts only bundled synthetic jobs and fixed review outcomes. Its SQLite database stays on the instance’s encrypted root volume. The Windows app and local standalone demonstration are available separately.

## One-time account setup

1. Create the empty private GitHub repository `dexterose1197/AutoDialer` and grant the Codex GitHub connection repository access. Codex will publish the existing source to `main` and set the four Actions variables once access is available.
2. Check whether AWS IAM already lists `token.actions.githubusercontent.com` under **Identity providers**. Open CloudFormation in **US East (N. Virginia)** and use **Create stack**, **Choose an existing template**, and **Upload a template file**. Upload the rendered `AutoDialer-EC2-pilot.yml`, name the stack `autodialer-pilot`, and leave the repository parameter at its default. Set **CreateGitHubOidcProvider** to `false` if the identity provider exists. Review the resource and IAM permission summary, acknowledge IAM resource creation, then create the stack after approving the cost. [CloudFormation console](https://us-east-1.console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks)
3. Return the stack name and its four **Outputs** to Codex. The outputs identify the deployment role, S3 release bucket, EC2 instance, and SSM command document. They are resource identifiers. Keep account passwords, access keys, and Tailscale auth keys out of chat and GitHub.
4. In the owner-only Tailscale network, enable MagicDNS and HTTPS certificates. Configure `tag:autodialer-pilot` with the owner as a tag administrator and grant the owner’s identity `tcp:443` access to that tag. Review broader grants that would otherwise cover the node. On Android, sign in to Tailscale using that owner identity. [Tailscale DNS settings](https://login.tailscale.com/admin/dns) · [Tailscale access controls](https://login.tailscale.com/admin/acls)
5. In GitHub **Actions → AutoDialer EC2 pilot**, run **pair** on `main`. Open the private enrollment URL shown in the job output and approve the tagged device. Run **pair** again to enable private HTTPS and obtain the Android URL. Run **deploy** on `main` and bookmark the printed URL in Android Chrome once the deploy succeeds.

The repository needs four Actions **variables** for deployment.

| CloudFormation output | GitHub Actions variable |
| --- | --- |
| `DeploymentRoleArn` | `EC2_PILOT_ROLE_ARN` |
| `ReleaseBucketName` | `EC2_PILOT_BUCKET` |
| `InstanceId` | `EC2_PILOT_INSTANCE_ID` |
| `CommandDocument` | `EC2_PILOT_COMMAND_DOCUMENT` |

## Test and operate from Android

- Turn on Tailscale, open the bookmarked URL in Chrome, and tap **Run demo**. Expect two classified records and one **Needs review**. Open the unclear response, play the recording, select **Unable to verify**, save, and export CSV. The header and export should report **Faster Whisper**.
- In EC2, restart the instance and check the same reviewed result is present. Test a second deployment after the first succeeds, then run **rollback** and check the result again. Rollback needs a previously successful deployment.
- From outside the Tailscale network, verify the private URL is unreachable. AWS should show no inbound rules on the instance’s security group.
- Use the EC2 console to **Stop instance** when the pilot is idle and **Start instance** when needed. The instance also stops seven days after its initial boot. Confirm the instance state is **Stopped** after expiry. An AWS public IP and the EC2 process can change on start. The Tailscale HTTPS name and SQLite volume remain.
- To remove the pilot after accepting that its synthetic records will be deleted, empty the CloudFormation-created release bucket in the S3 console, delete the pilot stack, and remove the tagged machine in Tailscale. Keep a pre-existing shared GitHub OIDC provider by using the stack’s reuse option during creation.

## Cost and implementation details

Using AWS’s published US East T3, gp3, and public IPv4 prices, seven continuous days are estimated at about **$8.16** before tax and transfer. The estimate includes about $7.02 for compute, $0.84 for the public IPv4 address, and $0.30 for 16 GiB of storage. S3 request and storage charges are additional. The proposed $10 target is an estimate allowance, and retained disk and artifacts can incur charges after compute stops. [T3 pricing](https://aws.amazon.com/ec2/instance-types/t3/) · [EBS pricing](https://aws.amazon.com/ebs/pricing/) · [Public IPv4 pricing](https://aws.amazon.com/vpc/pricing/)

GitHub OIDC trusts only this repository’s `main` branch. Its deployment role can upload release bundles and invoke one SSM command document on the pilot instance. SSM checks the release and model hashes, installs from the bundled wheelhouse, runs a real offline speech check, and swaps the running release only when that candidate is ready. An unhealthy service triggers a switch back to the previous release. The SQLite database is separate from the release directories.

To rebuild the uploadable template in Codex, run `python deploy/ec2/render_stack.py dist/AutoDialer-EC2-pilot.yml`. Changes to bootstrap scripts require a rendered template. Use Systems Manager to inspect cloud-init when a new instance has trouble registering.
