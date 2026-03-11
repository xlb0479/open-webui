<script lang="ts">
	import DOMPurify from 'dompurify';
	import { marked } from 'marked';

	import { toast } from 'svelte-sonner';

	import { onMount, getContext, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';

	import { getBackendConfig } from '$lib/apis';
	import {
		ldapUserSignIn,
		getSessionUser,
		userSignIn,
		userSignUp,
		updateUserTimezone
	} from '$lib/apis/auths';

	import { WEBUI_API_BASE_URL, WEBUI_BASE_URL } from '$lib/constants';
	import { WEBUI_NAME, config, user, socket } from '$lib/stores';

	import { generateInitialsImage, canvasPixelTest, getUserTimezone } from '$lib/utils';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import OnBoarding from '$lib/components/OnBoarding.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import { redirect } from '@sveltejs/kit';

	const i18n = getContext('i18n');

	let loaded = false;

	let mode = $config?.features.enable_ldap ? 'ldap' : 'signin';

	let form = null;

	let name = '';
	let email = '';
	let password = '';
	let confirmPassword = '';

	let ldapUsername = '';

	const setSessionUser = async (sessionUser, redirectPath: string | null = null) => {
		if (sessionUser) {
			console.log(sessionUser);
			toast.success($i18n.t(`You're now logged in.`));
			if (sessionUser.token) {
				localStorage.token = sessionUser.token;
			}
			$socket.emit('user-join', { auth: { token: sessionUser.token } });
			await user.set(sessionUser);
			await config.set(await getBackendConfig());

			// Update user timezone
			const timezone = getUserTimezone();
			if (sessionUser.token && timezone) {
				updateUserTimezone(sessionUser.token, timezone);
			}

			if (!redirectPath) {
				redirectPath = $page.url.searchParams.get('redirect') || '/';
			}

			goto(redirectPath);
			localStorage.removeItem('redirectPath');
		}
	};

	const signInHandler = async () => {
		const sessionUser = await userSignIn(email, password).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		await setSessionUser(sessionUser);
	};

	const signUpHandler = async () => {
		if ($config?.features?.enable_signup_password_confirmation) {
			if (password !== confirmPassword) {
				toast.error($i18n.t('Passwords do not match.'));
				return;
			}
		}

		const sessionUser = await userSignUp(name, email, password, generateInitialsImage(name)).catch(
			(error) => {
				toast.error(`${error}`);
				return null;
			}
		);

		await setSessionUser(sessionUser);
	};

	const ldapSignInHandler = async () => {
		const sessionUser = await ldapUserSignIn(ldapUsername, password).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		await setSessionUser(sessionUser);
	};

	const submitHandler = async () => {
		if (mode === 'ldap') {
			await ldapSignInHandler();
		} else if (mode === 'signin') {
			await signInHandler();
		} else {
			await signUpHandler();
		}
	};

	const oauthCallbackHandler = async () => {
		// Get the value of the 'token' cookie
		function getCookie(name) {
			const match = document.cookie.match(
				new RegExp('(?:^|; )' + name.replace(/([.$?*|{}()[\]\\/+^])/g, '\\$1') + '=([^;]*)')
			);
			return match ? decodeURIComponent(match[1]) : null;
		}

		const token = getCookie('token');
		if (!token) {
			return;
		}

		const sessionUser = await getSessionUser(token).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (!sessionUser) {
			return;
		}

		localStorage.token = token;
		await setSessionUser(sessionUser, localStorage.getItem('redirectPath') || null);
	};

	let onboarding = false;

	async function setLogoImage() {
		await tick();
		const logo = document.getElementById('logo');

		if (logo) {
			const isDarkMode = document.documentElement.classList.contains('dark');

			if (isDarkMode) {
				const darkImage = new Image();
				darkImage.src = `${WEBUI_BASE_URL}/static/favicon-dark.png`;

				darkImage.onload = () => {
					logo.src = `${WEBUI_BASE_URL}/static/favicon-dark.png`;
					logo.style.filter = ''; // Ensure no inversion is applied if favicon-dark.png exists
				};

				darkImage.onerror = () => {
					logo.style.filter = 'invert(1)'; // Invert image if favicon-dark.png is missing
				};
			}
		}
	}

	onMount(async () => {
		const redirectPath = $page.url.searchParams.get('redirect');
		if ($user !== undefined) {
			goto(redirectPath || '/');
		} else {
			if (redirectPath) {
				localStorage.setItem('redirectPath', redirectPath);
			}
		}

		const error = $page.url.searchParams.get('error');
		if (error) {
			toast.error(error);
		}

		await oauthCallbackHandler();
		form = $page.url.searchParams.get('form');
		// Allow previewing the login UI even when the backend config is unavailable.
		if (!form && !$config) {
			form = 'true';
		}

		loaded = true;
		setLogoImage();

		if (($config?.features.auth_trusted_header ?? false) || $config?.features.auth === false) {
			await signInHandler();
		} else {
			onboarding = $config?.onboarding ?? false;
		}
	});
</script>

<svelte:head>
	<title>
		{`${$WEBUI_NAME}`}
	</title>
</svelte:head>

<OnBoarding
	bind:show={onboarding}
	getStartedHandler={() => {
		onboarding = false;
		mode = $config?.features.enable_ldap ? 'ldap' : 'signup';
	}}
/>

<div class="relative min-h-[100dvh]" id="auth-page">
	<div class="absolute inset-0 bg-gray-50 dark:bg-black"></div>
	<div class="absolute inset-0 pointer-events-none overflow-hidden" aria-hidden="true">
		<div
			class="absolute -top-28 left-1/2 h-80 w-80 -translate-x-1/2 rounded-full bg-gray-200/70 dark:bg-gray-800/25 blur-3xl"
		/>
		<div
			class="absolute -bottom-28 right-[-4rem] h-80 w-80 rounded-full bg-gray-200/50 dark:bg-gray-800/20 blur-3xl"
		/>
		<div class="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-white/60 dark:to-black/60" />
	</div>
	<div class="w-full absolute top-0 left-0 right-0 h-8 drag-region" />

	{#if loaded}
		<div class="relative z-10 min-h-[100dvh] w-full flex items-center justify-center px-6 py-10" id="auth-container">
			<div class="w-full max-w-sm">
				{#if ($config?.features.auth_trusted_header ?? false) || $config?.features.auth === false}
					<div class="rounded-3xl bg-white/80 dark:bg-black/60 backdrop-blur ring-1 ring-gray-200/70 dark:ring-gray-800/70 px-6 py-10">
						<div class="flex items-center justify-center gap-3 text-[17px] font-medium tracking-tight text-gray-900 dark:text-gray-100">
							<span>{$i18n.t('Signing in to {{WEBUI_NAME}}', { WEBUI_NAME: $WEBUI_NAME })}</span>
							<Spinner className="size-5" />
						</div>
					</div>
				{:else}
					<div class="rounded-3xl bg-white/80 dark:bg-black/60 backdrop-blur ring-1 ring-gray-200/70 dark:ring-gray-800/70 p-6 text-gray-900 dark:text-gray-100">
						<div class="flex justify-center mb-4">
							<span
								class="inline-flex items-center rounded-full px-3 py-1 text-[11px] font-medium tracking-wide text-gray-700 dark:text-gray-300 ring-1 ring-gray-200/70 dark:ring-gray-800/70 bg-white/60 dark:bg-gray-950/30 backdrop-blur"
							>
								{$i18n.t('AI Workspace')}
							</span>
						</div>
							{#if $config?.metadata?.auth_logo_position === 'center'}
								<div class="flex justify-center mb-5">
									<img
										id="logo"
										crossorigin="anonymous"
										src="{WEBUI_BASE_URL}/static/favicon.png"
										class="size-16 rounded-2xl"
										alt="{$WEBUI_NAME} logo"
									/>
								</div>
							{/if}
							<form
								class="mt-1"
								on:submit={(e) => {
									e.preventDefault();
									submitHandler();
								}}
							>
								<div class="text-center">
									<div class="text-[28px] leading-tight font-semibold tracking-tight">
										{#if $config?.onboarding ?? false}
											{$i18n.t(`Get started with {{WEBUI_NAME}}`, { WEBUI_NAME: $WEBUI_NAME })}
										{:else if mode === 'ldap'}
											{$i18n.t(`Sign in to {{WEBUI_NAME}} with LDAP`, { WEBUI_NAME: $WEBUI_NAME })}
										{:else if mode === 'signin'}
											{$i18n.t(`Sign in to {{WEBUI_NAME}}`, { WEBUI_NAME: $WEBUI_NAME })}
										{:else}
											{$i18n.t(`Sign up to {{WEBUI_NAME}}`, { WEBUI_NAME: $WEBUI_NAME })}
										{/if}
									</div>

									{#if $config?.onboarding ?? false}
										<div class="mt-2 text-[13px] leading-relaxed text-gray-600 dark:text-gray-400">
											ⓘ {$WEBUI_NAME}
											{$i18n.t(
												'does not make any external connections, and your data stays securely on your locally hosted server.'
											)}
										</div>
									{/if}
								</div>

								{#if $config?.features.enable_login_form || $config?.features.enable_ldap || form}
									<div class="mt-6 space-y-3">
										{#if mode === 'signup'}
											<div>
												<label for="name" class="sr-only">{$i18n.t('Name')}</label>
												<input
													bind:value={name}
													type="text"
													id="name"
													class="w-full rounded-2xl px-4 py-3 text-[15px] bg-gray-100/80 dark:bg-gray-900/40 ring-1 ring-gray-200/70 dark:ring-gray-800/70 placeholder:text-gray-500 dark:placeholder:text-gray-500 focus:outline-hidden focus:ring-2 focus:ring-gray-900/20 dark:focus:ring-white/20"
													autocomplete="name"
													placeholder={$i18n.t('Name')}
													required
												/>
											</div>
										{/if}

										{#if mode === 'ldap'}
											<div>
												<label for="username" class="sr-only">{$i18n.t('Username')}</label>
												<input
													bind:value={ldapUsername}
													type="text"
													class="w-full rounded-2xl px-4 py-3 text-[15px] bg-gray-100/80 dark:bg-gray-900/40 ring-1 ring-gray-200/70 dark:ring-gray-800/70 placeholder:text-gray-500 dark:placeholder:text-gray-500 focus:outline-hidden focus:ring-2 focus:ring-gray-900/20 dark:focus:ring-white/20"
													autocomplete="username"
													name="username"
													id="username"
													placeholder={$i18n.t('Username')}
													required
												/>
											</div>
										{:else}
											<div>
												<label for="email" class="sr-only">{$i18n.t('Email')}</label>
												<input
													bind:value={email}
													type="email"
													id="email"
													class="w-full rounded-2xl px-4 py-3 text-[15px] bg-gray-100/80 dark:bg-gray-900/40 ring-1 ring-gray-200/70 dark:ring-gray-800/70 placeholder:text-gray-500 dark:placeholder:text-gray-500 focus:outline-hidden focus:ring-2 focus:ring-gray-900/20 dark:focus:ring-white/20"
													autocomplete="email"
													name="email"
													placeholder={$i18n.t('Email')}
													required
												/>
											</div>
										{/if}

										<div>
											<label for="password" class="sr-only">{$i18n.t('Password')}</label>
											<SensitiveInput
												bind:value={password}
												type="password"
												id="password"
												class="w-full rounded-2xl px-4 py-3 text-[15px] bg-gray-100/80 dark:bg-gray-900/40 ring-1 ring-gray-200/70 dark:ring-gray-800/70 placeholder:text-gray-500 dark:placeholder:text-gray-500 focus:outline-hidden focus:ring-2 focus:ring-gray-900/20 dark:focus:ring-white/20"
												placeholder={$i18n.t('Password')}
												autocomplete={mode === 'signup' ? 'new-password' : 'current-password'}
												name="password"
												screenReader={true}
												required
												aria-required="true"
											/>
										</div>

										{#if mode === 'signup' && $config?.features?.enable_signup_password_confirmation}
											<div>
												<label for="confirm-password" class="sr-only">{$i18n.t('Confirm Password')}</label>
												<SensitiveInput
													bind:value={confirmPassword}
													type="password"
													id="confirm-password"
													class="w-full rounded-2xl px-4 py-3 text-[15px] bg-gray-100/80 dark:bg-gray-900/40 ring-1 ring-gray-200/70 dark:ring-gray-800/70 placeholder:text-gray-500 dark:placeholder:text-gray-500 focus:outline-hidden focus:ring-2 focus:ring-gray-900/20 dark:focus:ring-white/20"
													placeholder={$i18n.t('Confirm Password')}
													autocomplete="new-password"
													name="confirm-password"
													required
												/>
											</div>
										{/if}
									</div>
								{/if}
								<div class="mt-5">
									{#if $config?.features.enable_login_form || $config?.features.enable_ldap || form}
										{#if mode === 'ldap'}
											<button
												class="w-full rounded-2xl px-4 py-3 text-[15px] font-medium bg-gray-900 text-white hover:bg-gray-800 dark:bg-white dark:text-gray-900 dark:hover:bg-gray-100 focus:outline-hidden focus:ring-2 focus:ring-gray-900/20 dark:focus:ring-white/20 transition"
												type="submit"
											>
												{$i18n.t('Authenticate')}
											</button>
										{:else}
											<button
												class="w-full rounded-2xl px-4 py-3 text-[15px] font-medium bg-gray-900 text-white hover:bg-gray-800 dark:bg-white dark:text-gray-900 dark:hover:bg-gray-100 focus:outline-hidden focus:ring-2 focus:ring-gray-900/20 dark:focus:ring-white/20 transition"
												type="submit"
											>
												{mode === 'signin'
													? $i18n.t('Sign in')
													: ($config?.onboarding ?? false)
														? $i18n.t('Create Admin Account')
														: $i18n.t('Create Account')}
											</button>

											{#if $config?.features.enable_signup && !($config?.onboarding ?? false)}
												<div class="mt-4 text-[13px] text-center text-gray-600 dark:text-gray-400">
													{mode === 'signin'
														? $i18n.t("Don't have an account?")
														: $i18n.t('Already have an account?')}

													<button
														class="ml-1 font-medium text-gray-900 dark:text-gray-200 underline underline-offset-4"
														type="button"
														on:click={() => {
															if (mode === 'signin') {
																mode = 'signup';
															} else {
																mode = 'signin';
															}
														}}
													>
														{mode === 'signin' ? $i18n.t('Sign up') : $i18n.t('Sign in')}
													</button>
												</div>
											{/if}
										{/if}
									{/if}
								</div>
							</form>

							{#if Object.keys($config?.oauth?.providers ?? {}).length > 0}
								<div class="flex items-center w-full">
									<hr class="flex-1 h-px my-5 border-0 bg-gray-200/70 dark:bg-gray-800/70" />
									{#if $config?.features.enable_login_form || $config?.features.enable_ldap || form}
										<span class="px-3 text-[12px] font-medium text-gray-500 dark:text-gray-400">
											{$i18n.t('or')}
										</span>
									{/if}
									<hr class="flex-1 h-px my-5 border-0 bg-gray-200/70 dark:bg-gray-800/70" />
								</div>
								<div class="flex flex-col space-y-2">
									{#if $config?.oauth?.providers?.google}
										<button
											class="w-full rounded-2xl px-4 py-3 text-[15px] font-medium ring-1 ring-gray-200/70 dark:ring-gray-800/70 bg-white/70 dark:bg-gray-950/30 hover:bg-white/90 dark:hover:bg-gray-950/45 focus:outline-hidden focus:ring-2 focus:ring-gray-900/20 dark:focus:ring-white/20 transition flex items-center justify-center"
											on:click={() => {
												window.location.href = `${WEBUI_BASE_URL}/oauth/google/login`;
											}}
										>
											<svg
												xmlns="http://www.w3.org/2000/svg"
												viewBox="0 0 48 48"
												class="size-5 mr-3"
												aria-hidden="true"
											>
												<path
													fill="#EA4335"
													d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
												/><path
													fill="#4285F4"
													d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
												/><path
													fill="#FBBC05"
													d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
												/><path
													fill="#34A853"
													d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
												/><path fill="none" d="M0 0h48v48H0z" />
											</svg>
											<span>{$i18n.t('Continue with {{provider}}', { provider: 'Google' })}</span>
										</button>
									{/if}
									{#if $config?.oauth?.providers?.microsoft}
										<button
											class="w-full rounded-2xl px-4 py-3 text-[15px] font-medium ring-1 ring-gray-200/70 dark:ring-gray-800/70 bg-white/70 dark:bg-gray-950/30 hover:bg-white/90 dark:hover:bg-gray-950/45 focus:outline-hidden focus:ring-2 focus:ring-gray-900/20 dark:focus:ring-white/20 transition flex items-center justify-center"
											on:click={() => {
												window.location.href = `${WEBUI_BASE_URL}/oauth/microsoft/login`;
											}}
										>
											<svg
												xmlns="http://www.w3.org/2000/svg"
												viewBox="0 0 21 21"
												class="size-5 mr-3"
												aria-hidden="true"
											>
												<rect x="1" y="1" width="9" height="9" fill="#f25022" /><rect
													x="1"
													y="11"
													width="9"
													height="9"
													fill="#00a4ef"
												/><rect x="11" y="1" width="9" height="9" fill="#7fba00" /><rect
													x="11"
													y="11"
													width="9"
													height="9"
													fill="#ffb900"
												/>
											</svg>
											<span>{$i18n.t('Continue with {{provider}}', { provider: 'Microsoft' })}</span
											>
										</button>
									{/if}
									{#if $config?.oauth?.providers?.github}
										<button
											class="w-full rounded-2xl px-4 py-3 text-[15px] font-medium ring-1 ring-gray-200/70 dark:ring-gray-800/70 bg-white/70 dark:bg-gray-950/30 hover:bg-white/90 dark:hover:bg-gray-950/45 focus:outline-hidden focus:ring-2 focus:ring-gray-900/20 dark:focus:ring-white/20 transition flex items-center justify-center"
											on:click={() => {
												window.location.href = `${WEBUI_BASE_URL}/oauth/github/login`;
											}}
										>
											<svg
												xmlns="http://www.w3.org/2000/svg"
												viewBox="0 0 24 24"
												class="size-5 mr-3"
												aria-hidden="true"
											>
												<path
													fill="currentColor"
													d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.92 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57C20.565 21.795 24 17.31 24 12c0-6.63-5.37-12-12-12z"
												/>
											</svg>
											<span>{$i18n.t('Continue with {{provider}}', { provider: 'GitHub' })}</span>
										</button>
									{/if}
									{#if $config?.oauth?.providers?.oidc}
										<button
											class="w-full rounded-2xl px-4 py-3 text-[15px] font-medium ring-1 ring-gray-200/70 dark:ring-gray-800/70 bg-white/70 dark:bg-gray-950/30 hover:bg-white/90 dark:hover:bg-gray-950/45 focus:outline-hidden focus:ring-2 focus:ring-gray-900/20 dark:focus:ring-white/20 transition flex items-center justify-center"
											on:click={() => {
												window.location.href = `${WEBUI_BASE_URL}/oauth/oidc/login`;
											}}
										>
											<svg
												xmlns="http://www.w3.org/2000/svg"
												fill="none"
												viewBox="0 0 24 24"
												stroke-width="1.5"
												stroke="currentColor"
												class="size-5 mr-3"
												aria-hidden="true"
											>
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													d="M15.75 5.25a3 3 0 0 1 3 3m3 0a6 6 0 0 1-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1 1 21.75 8.25Z"
												/>
											</svg>

											<span
												>{$i18n.t('Continue with {{provider}}', {
													provider: $config?.oauth?.providers?.oidc ?? 'SSO'
												})}</span
											>
										</button>
									{/if}
									{#if $config?.oauth?.providers?.feishu}
										<button
											class="w-full rounded-2xl px-4 py-3 text-[15px] font-medium ring-1 ring-gray-200/70 dark:ring-gray-800/70 bg-white/70 dark:bg-gray-950/30 hover:bg-white/90 dark:hover:bg-gray-950/45 focus:outline-hidden focus:ring-2 focus:ring-gray-900/20 dark:focus:ring-white/20 transition flex items-center justify-center"
											on:click={() => {
												window.location.href = `${WEBUI_BASE_URL}/oauth/feishu/login`;
											}}
										>
											<span>{$i18n.t('Continue with {{provider}}', { provider: 'Feishu' })}</span>
										</button>
									{/if}
								</div>
							{/if}

							{#if $config?.features.enable_ldap && $config?.features.enable_login_form}
								<div class="mt-2">
									<button
										class="w-full text-center text-[12px] font-medium text-gray-600 dark:text-gray-400 underline underline-offset-4"
										type="button"
										on:click={() => {
											if (mode === 'ldap')
												mode = ($config?.onboarding ?? false) ? 'signup' : 'signin';
											else mode = 'ldap';
										}}
									>
										<span
											>{mode === 'ldap'
												? $i18n.t('Continue with Email')
												: $i18n.t('Continue with LDAP')}</span
										>
									</button>
								</div>
							{/if}
						</div>
						{#if $config?.metadata?.login_footer}
							<div class="max-w-sm mx-auto">
								<div class="mt-3 text-[0.7rem] text-gray-500 dark:text-gray-400 marked">
									{@html DOMPurify.sanitize(marked($config?.metadata?.login_footer))}
								</div>
							</div>
						{/if}
				{/if}
			</div>
			</div>

		{#if !$config?.metadata?.auth_logo_position}
			<div class="fixed m-10 z-50">
				<div class="flex space-x-2">
					<div class=" self-center">
						<img
							id="logo"
							crossorigin="anonymous"
							src="{WEBUI_BASE_URL}/static/favicon.png"
							class=" w-6 rounded-full"
							alt=""
						/>
					</div>
				</div>
			</div>
		{/if}
	{/if}
</div>
