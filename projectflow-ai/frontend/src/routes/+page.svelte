<script lang="ts">
  import { onMount } from 'svelte';
  import { auth } from '$lib/stores/auth';
  import { goto } from '$app/navigation';

  onMount(() => {
    // Redirect to projects if already authenticated
    if ($auth.isAuthenticated) {
      goto('/projects');
    }
  });
</script>

<div class="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
  <div class="max-w-md w-full space-y-8">
    <div>
      <h2 class="mt-6 text-center text-3xl font-extrabold text-gray-900">
        Welcome to ProjectFlow AI
      </h2>
      <p class="mt-2 text-center text-sm text-gray-600">
        AI-augmented project workspace with Kanban workflow
      </p>
    </div>
    
    <div class="mt-8 space-y-6">
      <div class="space-y-4">
        <a 
          href="/login"
          class="group relative w-full flex justify-center py-2 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
        >
          Sign in to your account
        </a>
        
        <a 
          href="/register"
          class="group relative w-full flex justify-center py-2 px-4 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
        >
          Create new account
        </a>
      </div>
      
      <div class="mt-6">
        <div class="relative">
          <div class="absolute inset-0 flex items-center">
            <div class="w-full border-t border-gray-300"></div>
          </div>
          <div class="relative flex justify-center text-sm">
            <span class="px-2 bg-gray-50 text-gray-500">Features</span>
          </div>
        </div>
        
        <div class="mt-6 grid grid-cols-1 gap-3">
          <div class="text-center">
            <h3 class="text-lg font-medium text-gray-900">Kanban Boards</h3>
            <p class="mt-2 text-sm text-gray-600">
              Organize tasks with drag-and-drop Kanban boards
            </p>
          </div>
          
          <div class="text-center">
            <h3 class="text-lg font-medium text-gray-900">AI Integration</h3>
            <p class="mt-2 text-sm text-gray-600">
              AI agents help automate and accelerate your workflow
            </p>
          </div>
          
          <div class="text-center">
            <h3 class="text-lg font-medium text-gray-900">Real-time Collaboration</h3>
            <p class="mt-2 text-sm text-gray-600">
              Work together with live updates and CRDT sync
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>