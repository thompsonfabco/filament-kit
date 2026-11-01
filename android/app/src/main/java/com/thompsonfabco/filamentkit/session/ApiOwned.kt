package com.thompsonfabco.filamentkit.session

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import kotlin.reflect.KClass
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch

/**
 * A ViewModel that lives exactly as long as one value of [keys] (in the app: one [com.thompsonfabco.filamentkit.net.Api],
 * i.e. one pinned client). When the key changes or becomes null, the old instance is cleared (its `viewModelScope`
 * is cancelled, so no loop or call keeps using the old client) and a new one is created with [build].
 */
class ApiOwned<K : Any, T : ViewModel>(
    scope: CoroutineScope,
    keys: Flow<K?>,
    private val type: KClass<T>,
    private val build: (K) -> T,
) {
    private val _current = MutableStateFlow<T?>(null)
    val current: StateFlow<T?> = _current.asStateFlow()

    private var store: ViewModelStore? = null

    init {
        scope.launch {
            keys.distinctUntilChanged { a, b -> a === b }.collect { key -> swap(key) }
        }
    }

    private fun swap(key: K?) {
        close()
        if (key == null) return
        val s = ViewModelStore()
        store = s
        _current.value = ViewModelProvider(s, Factory { build(key) })[type.java]
    }

    private class Factory(private val make: () -> ViewModel) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <V : ViewModel> create(modelClass: Class<V>): V = make() as V
    }

    /** Clears the current instance (also call when the owner is cleared). */
    fun close() {
        _current.value = null
        store?.clear()
        store = null
    }
}
